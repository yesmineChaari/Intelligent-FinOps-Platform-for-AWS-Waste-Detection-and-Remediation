# FinOps Dashboard

Next.js 15 dashboard with two views: a **Business dashboard** (cost & savings overview) and an **Engineer interface** (pipeline details, LLM analysis, infrastructure PRs). All data is read-only — the dashboard never writes to the database or GitHub.

---

## Stack

| Layer | Technology |
|---|---|
| Framework | Next.js 15 (App Router) |
| Language | TypeScript |
| Styling | Tailwind CSS |
| Charts | Recharts v3 |
| Database client | `@neondatabase/serverless` (HTTP driver) |
| Icons | lucide-react |

---

## Environment variables

Stored in `.env.local` (never committed).

| Variable | Description |
|---|---|
| `NEON_DATABASE_URL` | Neon PostgreSQL connection string (`sslmode=require`) |
| `GITHUB_TOKEN` | Personal access token with **Pull requests: read** on `finops-infra` |
| `GITHUB_REPO` | Repository slug, e.g. `Nour-Ben-Hadid/finops-infra` |

---

## API endpoints

All endpoints live under `src/app/api/`. They run server-side — DB credentials and the GitHub token are never exposed to the browser.

### `GET /api/costs`

Aggregates savings potential across all runs for the Business dashboard metric cards and chart.

**Neon tables:**

| Table | Usage |
|---|---|
| `optimization_runs` | Counts completed vs total runs |
| `phase1_ec2_outputs` | Sums `waste_per_month` for EC2 savings total; groups by `waste_type` + `action` for the breakdown chart |
| `phase1_s3_outputs` | Sums `metrics->>'estimated_monthly_savings'` (stored as JSONB) for S3 savings total; counts flagged buckets |

---

### `GET /api/runs`

Returns the 50 most recent optimization runs for the runs table and the Engineer run selector.

**Neon tables:**

| Table | Usage |
|---|---|
| `optimization_runs` | Base rows: `id`, `status`, `started_at`, `completed_at`, `workspace_key`, `phase3_model_key` |
| `phase1_ec2_outputs` | LEFT JOINed to count flagged EC2 instances and sum savings per run |
| `phase1_s3_outputs` | LEFT JOINed to count flagged S3 buckets and sum savings per run |

---

### `GET /api/phases/[runId]`

Returns all three phase outputs for a selected run. Used by the Engineer interface Phase 1 and Phase 2 tabs.

**Neon tables:**

| Table | Usage |
|---|---|
| `phase1_ec2_outputs` | EC2 waste detections: instance name, role, action, waste type, instance type change, cost delta, detection reason, CPU/RAM metrics (JSONB) |
| `phase1_s3_outputs` | S3 waste detections: bucket name, action, waste type, detection reason, estimated savings from `metrics` JSONB, lifecycle policy |
| `phase2_ec2_outputs` | Guardrail decisions: original vs final action, blast radius score, relationship count, whether the action was downgraded and why |

---

### `GET /api/llm/[runId]`

Returns LLM analysis outputs for a selected run. Used by the Engineer interface LLM Report tab. Only populated when the pipeline ran with `PHASE3_MODEL` set.

**Neon tables:**

| Table | Usage |
|---|---|
| `waste` | EC2 LLM verdicts (`APPROVE`/`BLOCK`/`REVIEW`), `technical_explanation`, `decision_rationale`, `cost_report` (JSONB), `risk_assessment` (JSONB), `terraform_action`, `terraform_block` (HCL patch content) |
| `s3_waste` | Same fields as `waste` but for S3 bucket findings |
| `resources` | LEFT JOINed on `waste.resource_id` to resolve the human-readable resource name |

---

### `GET /api/prs`

Fetches pull requests from the `finops-infra` Terraform repository. No database involved.

**GitHub REST API:**

```
GET https://api.github.com/repos/{GITHUB_REPO}/pulls?state=all&per_page=50&sort=created&direction=desc
```

**Headers sent:**
- `Authorization: Bearer {GITHUB_TOKEN}`
- `Accept: application/vnd.github+json`
- `X-GitHub-Api-Version: 2022-11-28`

**Fields returned per PR:** `id`, `number`, `title`, `state`, `draft`, `html_url`, `head.ref`, `base.ref`, `created_at`, `updated_at`, `merged_at`, `user.login`

Responses are cached for 60 seconds (`next: { revalidate: 60 }`).

---

## Neon DB schema reference

These tables are defined in `pfa/migrations/001_phase_output_traceability.sql` and created at runtime by `pfa/persistence/phase_outputs.py`.

```
optimization_runs         — one row per pipeline execution
phase1_ec2_outputs        — one row per EC2 instance flagged in Phase 1
phase1_s3_outputs         — one row per S3 bucket flagged in Phase 1
phase2_ec2_outputs        — one row per EC2 instance after guardrail evaluation
waste                     — one row per EC2 resource processed by Phase 3 LLM
s3_waste                  — one row per S3 bucket processed by Phase 3 LLM
resources                 — resource registry (from finops-project ingestion service)
```

> **Note:** `estimated_monthly_savings` for S3 is not a top-level column in `phase1_s3_outputs`. It is stored inside the `metrics` JSONB field and accessed as `metrics->>'estimated_monthly_savings'`.

---

## Pages

| Route | View | Data sources |
|---|---|---|
| `/` | Business dashboard | `/api/costs`, `/api/runs` |
| `/engineer` | Engineer interface | `/api/runs`, `/api/phases/:id`, `/api/llm/:id`, `/api/prs` |

---

## Running locally

```bash
cd pfa/application
npm install
npm run dev        # http://localhost:3001
```
