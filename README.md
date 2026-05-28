# AWS FinOps Agent Pipeline

This project detects AWS cost waste, applies deterministic guardrails, and can
send resulting recommendations through an LLM/Terraform review stage. The
preferred deployment is a Redis-coordinated, multi-container pipeline; the
original single-process entrypoint remains available for local compatibility.

## Architecture

```text
Agent0 --ingestion_complete--> Redis --> Agent1 --deterministic_complete(run_id)--> Redis --> Agent2
  |                                      |                                              |
  +-------------------------- External Postgres/Neon ----------------------------------+
                               stored inputs, outputs, and run status
```

Redis carries event metadata only. Inventory, deterministic outputs, and Phase
3 results are stored in Postgres/Neon.

| Component | Responsibility | Entrypoint |
| --- | --- | --- |
| `agent0` | LocalStack/AWS discovery and metric ingestion; publishes `ingestion_complete` | `agent0/app/main.py` |
| `agent1` | EC2/S3 Phase 1 detection and EC2 Phase 2 guardrails | `python -m agent1.main` |
| `agent2` | Phase 3 LLM/Terraform evaluation and optional PR flow | `python -m agent2.main` |
| `shared` | DB, Redis events, settings, contracts, and persistence | Python package |
| `main.py` | Legacy one-process Phase 1 -> Phase 2 -> Phase 3 execution | `python main.py` |

## Source Layout

```text
.
|-- agent0/app/                  # Ingestion API/scheduler container
|-- agent1/
|   |-- main.py                  # Deterministic worker
|   |-- phase1/                  # Real Phase 1 implementation
|   `-- phase2/                  # Real Phase 2 implementation
|-- agent2/
|   |-- main.py                  # Phase 3 worker
|   |-- phase3/                  # Real Phase 3 implementation
|   `-- llm_benchmarking/        # Embedded IaC evaluation workflow
|-- shared/                      # Shared infrastructure and persistence APIs
|-- persistence/                 # Legacy compatibility exports to shared.persistence
|-- phase1/ phase2/ phase3/     # Legacy compatibility wrappers
|-- llm_benchmarking/            # Legacy benchmark access wrappers
|-- docker-compose.yml           # Full containerized stack
|-- rules.yaml                   # Detection and guardrail rules
|-- tests/                       # unittest coverage
`-- docs/                        # Operations and persistence documentation
```

New code should prefer imports from `agent1.*`, `agent2.*`, and `shared.*`.
Root `phase1`, `phase2`, `phase3`, `llm_benchmarking`, and `persistence`
imports remain for legacy compatibility.

## Containerized Mode

The root Compose stack runs Redis, LocalStack, Agent0, Agent1, and Agent2.
Neon/Postgres remains external.

1. Create `.env` locally. Do not commit it.
2. Provide `DATABASE_URL` for Agent0 and Agent1. Agent2 also accepts
   `NEON_DATABASE_URL`.
3. Provide provider or GitHub credentials only when the enabled Phase 3 flow
   needs them.

```powershell
docker compose build
docker compose config --quiet
docker compose up
```

Useful manual worker modes:

```powershell
# Run deterministic processing without waiting for Agent0's Redis event.
docker compose run --rm -e AGENT1_SKIP_WAIT=1 agent1

# Run Phase 3 for an already persisted run.
docker compose run --rm -e AGENT2_RUN_ID=123 agent2
```

See [docs/dockerisation.md](docs/dockerisation.md) for the full smoke-test
checklist, event payload contract, status lifecycle, and troubleshooting.

## Legacy Mode

`main.py` continues to run Phase 1, Phase 2, and Phase 3 in one process for
compatibility and local debugging.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:NEON_DATABASE_URL="postgresql://..."
$env:SKIP_REDIS_TRIGGER="1"
python main.py
```

Without `SKIP_REDIS_TRIGGER=1`, the legacy entrypoint waits for an
`ingestion_complete` event on Redis.

## Configuration

Common configuration values:

| Variable | Used by | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Agent0, Agent1, Agent2 | External Postgres/Neon connection; required by Agent0 and Agent1 |
| `NEON_DATABASE_URL` | Agent2, legacy `main.py` | Alternative/legacy database URL |
| `REDIS_URL` | Agent0, Agent1, Agent2, legacy `main.py` | Redis Stream connection |
| `RULES_PATH` | Agent1, legacy `main.py` | Rules file; defaults to `rules.yaml` |
| `AGENT1_SKIP_WAIT` | Agent1 | Run without waiting for `ingestion_complete` |
| `AGENT2_RUN_ID` | Agent2 | Run Phase 3 manually for a stored run |
| `PHASE3_MODEL` | Agent2, legacy `main.py` | LLM model selection |
| `PHASE3_TERRAFORM_REPO_URL`, `PHASE3_TERRAFORM_REF`, `PHASE3_TERRAFORM_SUBDIR` | Agent0/Agent1/Agent2 | Terraform source metadata passed through events or environment |
| `WORKSPACE_KEY`, `TERRAFORM_WORKSPACE_KEY`, `ACCOUNT_ID` | Agent0 | Optional safe metadata for `ingestion_complete` |
| `GROQ_API_KEY`, `GOOGLE_API_KEY`, `MISTRAL_API_KEY` | Agent2 | LLM provider credentials when used |
| `GITHUB_TOKEN` | Agent2 | Optional for public GitHub reads; required for PR creation and authenticated access |
| `PHASE3_CREATE_PR` | Agent2 | Set to `1` only to enable PR creation; default is disabled |
| `PHASE3_PATCH_SOURCE` | Agent2 | Phase 3 patch source mode: `auto`, `static`, or `llm`; defaults to `auto` |
| `PHASE3_LLM_CODEGEN_SAFE_TOKENS` | Agent2 | Approximate prompt-token limit for trusting LLM-generated Terraform; defaults to `6000` |

Never commit `.env`, provider keys, database URLs, Redis credentials, Terraform
state, or generated secret-bearing output.

See [docs/phase3_static_patch_fallback.md](docs/phase3_static_patch_fallback.md)
for the Phase 3 LLM/static patch source safety mode.

## Event Flow

| Stream | Event | Producer | Consumer | Payload |
| --- | --- | --- | --- | --- |
| `ingestion_stream` | `ingestion_complete` | Agent0 | Agent1 | `status`, optional workspace/account/Terraform metadata |
| `optimization_stream` | `deterministic_complete` | Agent1 | Agent2 | `run_id`, `status`, optional safe metadata |
| `optimization_stream` | `phase3_complete` / `phase3_failed` | Agent2 | Operators/downstream users | `run_id` when known, status, safe failure text |

Agent0 does not publish database contents or AWS inventory through Redis.
Redis publication failure is logged as a warning and does not undo completed
ingestion data.

The `deterministic_complete` event status is `phase2_completed`, describing the
event milestone. At that point the persisted run status is `waiting_phase3`.

## Persistence

An optimization run moves through:

```text
running_phase1 -> running_phase2 -> waiting_phase3 -> running_phase3 -> completed
```

Failure outcomes are `failed` for Agent1 failures and `phase3_failed` for
Agent2 failures. Key tables are `optimization_runs`, `phase1_ec2_outputs`,
`phase1_s3_outputs`, `phase2_ec2_outputs`, `waste`, and `s3_waste`.

See [docs/output_persistence.md](docs/output_persistence.md) for table roles
and stored output details.

## Development

Run tests without external services:

```powershell
python -m unittest discover -s tests
```

The Agent2-owned embedded benchmark is located at:

```powershell
cd agent2\llm_benchmarking\IaC-Evaluation-Pipeline
pip install -r requirements.txt
python pipeline.py --models qwen3-coder-32b --scenario A1
python scorer.py
```

Terraform and OPA must be available separately when benchmark validators or
Phase 3 behavior require them.
