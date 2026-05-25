# Dashboard Backend

This folder contains a read-only FastAPI API for the FinOps dashboard. It
queries persisted pipeline output and Agent0 inventory/telemetry tables; it
does not run phases, write pipeline output, or expose direct database access
to the React application.

## Run Locally

From the repository root:

```powershell
cd dashboard_backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `DATABASE_URL` in `.env` to a read-capable Neon/Postgres connection. Set
`FRONTEND_ORIGIN` if Vite is served from a URL other than
`http://localhost:5173`. Keep `.env` untracked.

Start the API from `dashboard_backend/`:

```powershell
uvicorn app.main:app --reload
```

Start the dashboard in a separate terminal:

```powershell
cd dashboard
Copy-Item .env.example .env
# Set VITE_USE_MOCKS=false in .env to use FastAPI.
npm run dev
```

With `VITE_USE_MOCKS=true` or no frontend environment configuration, the
dashboard continues to use its existing mock fixtures.

## Endpoints

All dashboard routes are served under `/api/v1`:

| Endpoint | Source |
| --- | --- |
| `GET /overview` | Latest-run aggregates and derived alerts |
| `GET /ec2/findings` | Phase 1/2 EC2 output with inventory and telemetry joins |
| `GET /s3/findings` | Phase 1 S3 output with inventory joins |
| `GET /guardrails` | Phase 2 EC2 decisions |
| `GET /phase3/reviews` | EC2 and S3 Phase 3 decision output |
| `GET /alerts` | Derived failure/block/parse-error notices |
| `GET /runs` | Optimization run history and aggregate counts |

For example, the full EC2 endpoint is
`http://localhost:8000/api/v1/ec2/findings`.

## Database Sources

The persisted output schema is defined at runtime by
`shared/persistence/phase_outputs.py`. The backend queries these existing
tables:

| Table | Data used by dashboard |
| --- | --- |
| `optimization_runs` | run id, status, error message, start/completion time |
| `phase1_ec2_outputs` | EC2 findings, metrics JSON, proposed type, savings |
| `phase1_s3_outputs` | S3 findings, lifecycle proposal, metrics JSON, savings |
| `phase2_ec2_outputs` | final guardrail action, blast radius, block reason, savings |
| `waste` | Phase 3 EC2 verdict, Terraform fields, explanation, parse error |
| `s3_waste` | Phase 3 S3 verdict, Terraform fields, explanation, parse error |

The backend also reads Agent0 tables already referenced by the ingestion and
detection code:

| Table | Data used by dashboard |
| --- | --- |
| `resources` | resource display name for Phase 3 EC2 rows |
| `ec2_instances` | region and recorded EC2 instance type |
| `s3_instances` | bucket region, object count, and size |
| `ec2_metrics` | CPU and RAM dashboard aggregates |

No new database tables or writes are introduced by this API.

## Field Provenance

Values available directly from persisted data include run statuses and
timestamps, EC2/S3 finding actions and reasons, saved monthly estimates,
Phase 2 block and blast-radius details, and Phase 3 verdict/Terraform/parse
fields. Regions and resource footprint are read from existing Agent0
inventory tables.

The following fields are calculated for presentation:

- Overview KPI totals, counts, finding-type groupings, and trend points are
  aggregates over persisted runs and outputs.
- EC2 average CPU and average memory are aggregates over `ec2_metrics`; CPU
  p95 uses saved Phase 1 metrics where present, with telemetry as fallback.
- Risk/status badges and guardrail outcome labels are mapped from Phase 2
  action, block reason, and blast-radius values.
- Runs-history duration, finding counts, blocked count, parse-error count,
  and total savings are query-time aggregates.
- `terraformBlock` is a boolean indicating whether stored Terraform text is
  present.

The following data is not currently persisted as a dashboard field:

- S3 storage class is returned as `Unavailable`; the saved S3 finding does not
  store a selected storage class value.
- There is no alerts table. `/alerts` returns read-only derived notices from
  failed optimization runs, blocked/review guardrails, and Phase 3 parse
  failures. If none exist, the result is an empty list.

## Read-Only Boundary

Database access is performed through `app/db.py` in read-only transactions.
Endpoint repository functions issue `SELECT` queries only. The phase workers,
pipeline persistence behavior, and existing database writes are unchanged.
