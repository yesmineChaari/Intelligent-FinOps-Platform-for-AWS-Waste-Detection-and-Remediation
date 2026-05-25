# Containerized Agents

The root `docker-compose.yml` runs the full split deployment: Redis, Agent0,
Agent1, Agent2, and LocalStack for Agent0's existing ingestion environment.
Keep database credentials and provider keys in `.env`; Neon/Postgres remains an
external service. `DATABASE_URL` is required by Agent0 and Agent1, and Agent2
accepts `DATABASE_URL` or `NEON_DATABASE_URL`.

## Execution Modes

The root `main.py` remains the legacy single-process entrypoint for local
debugging and compatibility. It runs Phase 1, Phase 2, and Phase 3 in the same
process:

```powershell
python main.py
```

For the containerized architecture, use the worker entrypoints through
Compose. Agent1 runs Phase 1 and Phase 2, and Agent2 runs Phase 3:

```powershell
docker compose build
docker compose up
```

The split responsibilities are:

- Agent0 collects ingestion and AWS inventory/metric data.
- Agent1 runs deterministic Phase 1 and Phase 2 only.
- Agent2 runs Phase 3 LLM/Terraform processing only.
- `shared/` contains common persistence, database, Redis event, settings, and contract code.

The source ownership follows those boundaries: real Phase 1 and Phase 2 code
lives under `agent1/`, real Phase 3 and benchmarking code lives under
`agent2/`, and the root `phase*`, `persistence`, and `llm_benchmarking`
packages are legacy compatibility wrappers.

## Smoke-Test Checklist

### 1. Prerequisites

- Install Docker with Docker Compose support.
- Create a local `.env` file and do not commit it.
- Set `DATABASE_URL` for Agent0 and Agent1; Agent2 can use `DATABASE_URL` or `NEON_DATABASE_URL`.
- Set LLM provider keys only when Phase 3 will call those providers.
- Set `GITHUB_TOKEN` only when the configured Phase 3 flow creates a GitHub pull request.

### 2. Build And Validate

From the repository root:

```powershell
docker compose build
docker compose config --quiet
```

### 3. Start The Full Stack

```powershell
docker compose up
```

`depends_on` establishes startup order only; it does not establish service
readiness or workflow completion.

### 4. Verify Event Flow

The event-driven workflow is:

1. Agent0 publishes `ingestion_complete`.
2. Agent1 consumes `ingestion_complete`.
3. Agent1 runs Phase 1 and Phase 2, persists their outputs, and publishes `deterministic_complete` with `run_id`.
4. Agent2 consumes `deterministic_complete`.
5. Agent2 loads stored Phase 1 and Phase 2 outputs, runs Phase 3, and publishes `phase3_complete` or `phase3_failed`.

Redis carries event metadata only, including `run_id`; the database stores the
actual phase outputs.

Agent0 publishes only after its ingestion cycle reaches its existing completed
path. An initial discovery failure prevents an event. If Redis publication
fails after data ingestion, Agent0 logs a safe warning and does not discard
the database result.

Event contracts:

| Stream | Event | Required fields | Optional safe metadata |
| --- | --- | --- | --- |
| `ingestion_stream` | `ingestion_complete` | `event`, `status=completed` | `workspace_key`, `account_id`, `terraform_repo_url`, `terraform_ref`, `terraform_subdir` |
| `optimization_stream` | `deterministic_complete` | `event`, `run_id`, `status=phase2_completed` | workspace/account/Terraform metadata |
| `optimization_stream` | `phase3_complete` | `event`, `run_id`, `status=completed` | None |
| `optimization_stream` | `phase3_failed` | `event`, `status=phase3_failed`, safe `error_message` | `run_id` when known |

Agent0 sources optional metadata from `WORKSPACE_KEY` (or
`TERRAFORM_WORKSPACE_KEY`), `ACCOUNT_ID`, `PHASE3_TERRAFORM_REPO_URL`,
`PHASE3_TERRAFORM_REF`, and `PHASE3_TERRAFORM_SUBDIR`. It never forwards raw
inventory or credential values. The `deterministic_complete` event carries
`status=phase2_completed`, while the durable run status is `waiting_phase3`
until Agent2 begins.

Monitor the workers and inspect the metadata streams:

```powershell
docker compose logs -f agent0 agent1 agent2
docker compose exec redis redis-cli XRANGE ingestion_stream - + COUNT 5
docker compose exec redis redis-cli XRANGE optimization_stream - + COUNT 10
```

### 5. Manual Worker Runs

Agent0 now publishes `ingestion_complete` when an ingestion cycle reaches its
completed path.
For debugging, or to run Agent1 independently after data has already been
populated, bypass the Redis wait:

```powershell
docker compose run --rm -e AGENT1_SKIP_WAIT=1 agent1
```

After Agent1 creates a known optimization run, run Agent2 manually by run id:

```powershell
docker compose run --rm -e AGENT2_RUN_ID=123 agent2
```

The standalone `agent0/docker-compose.yml` remains useful for collector-only
development. It does not provide Redis by default; when `REDIS_URL` is absent,
Agent0 logs a warning and safely skips event publication.

### 6. Inspect Persistence

Inspect these external Postgres/Neon tables after a run:

- `optimization_runs`
- `phase1_ec2_outputs`
- `phase1_s3_outputs`
- `phase2_ec2_outputs`
- `waste`
- `s3_waste`

The expected `optimization_runs.status` values are:

- `running_phase1`
- `running_phase2`
- `waiting_phase3`
- `running_phase3`
- `completed`
- `failed`
- `phase3_failed`

### 7. Review Log Safety

Before sharing logs, confirm they do not contain:

- Full `DATABASE_URL` or `NEON_DATABASE_URL` values
- `GITHUB_TOKEN`
- LLM API keys
- Full Terraform file contents
- `terraform.tfstate` contents
- Secrets loaded from `.env`

## Troubleshooting

- `DATABASE_URL` or `NEON_DATABASE_URL` missing: add the required external database URL to `.env`; Agent1 requires `DATABASE_URL`, while Agent2 accepts either name.
- Redis connection failure: verify the `redis` service is running and Agent0, Agent1, and Agent2 receive `REDIS_URL=redis://redis:6379`.
- Agent1 waits indefinitely: verify Agent0 completed ingestion and did not log a Redis publication warning; use skip mode after ingestion data exists for manual debugging:

```powershell
docker compose run --rm -e AGENT1_SKIP_WAIT=1 agent1
```

- Agent2 manual execution fails: provide a valid integer run id using `-e AGENT2_RUN_ID=123` after Agent1 has persisted output rows.
- Phase 3 credentials fail: configure only the required LLM provider key and, when pull request creation is enabled, a valid `GITHUB_TOKEN`.
- Docker build dependency installation fails: inspect the failing `pip` or system package step, verify network/package index access, and rebuild the affected service.

The existing `agent0/docker-compose.yml` remains available for Agent0-only
development; the root `docker-compose.yml` is for the complete multi-container
solution.
