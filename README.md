# AWS FinOps Agent Pipeline

This repository contains a Python pipeline that detects AWS cost waste, applies graph-aware guardrails, and optionally sends the final Agent 2 decisions to an LLM-based validation layer. The root project is the live agent. The `llm_benchmarking/IaC-Evaluation-Pipeline/` folder is an embedded benchmark used by Phase 3.

## Repository Tree

```text
.
|-- main.py                         # Async entrypoint for Phase 1, Phase 2, and Phase 3
|-- rules.yaml                      # Detection thresholds, sizing limits, and guardrail rules
|-- requirements.txt                # Root agent Python dependencies
|-- AGENTS.md                       # Contributor and coding guidelines
|-- phase1/                         # Raw waste detection and sizing logic
|   |-- loader.py                   # Loads and validates rules.yaml
|   |-- models.py                   # EC2 detection result and rule models
|   |-- queries.py                  # EC2 inventory and metrics queries
|   |-- detection.py                # EC2 zombie, idle, oversized, and clean detection
|   |-- sizing.py                   # EC2 downsize recommendation helpers
|   |-- s3_models.py                # S3 detection result and rule models
|   |-- s3_queries.py               # S3 inventory, metrics, and sample queries
|   `-- s3_detection.py             # S3 lifecycle and storage mismatch detection
|-- phase2/                         # Agent 2 graph guardrails for EC2 findings
|   |-- models.py                   # RelationshipEdge and Phase2Result models
|   |-- queries.py                  # Relationship graph query helpers
|   `-- guardrails.py               # Blast radius scoring and action downgrades
|-- phase3/                         # LLM validation integration
|   |-- converter.py                # Converts Phase 1/2 results into benchmark scenarios
|   `-- llm_phase3.py               # Loads benchmark runners and executes the selected model
|-- tests/                          # unittest regression tests
|-- llm_benchmarking/
|   `-- IaC-Evaluation-Pipeline/    # Embedded LLM benchmark project
|       |-- pipeline.py             # Runs models against benchmark scenarios
|       |-- scorer.py               # Builds the leaderboard
|       |-- config.py               # Model/provider config and paths
|       |-- scenarios/              # Tier A-D benchmark scenario JSON
|       |-- prompts/                # Prompt builders and judge prompts
|       |-- runners/                # Groq, Google, Mistral runner implementations
|       |-- validators/             # Terraform, Checkov, OPA, NL, and ordering validators
|       |-- policies/               # OPA Rego policies
|       |-- outputs/                # Per-model scenario outputs
|       |-- results/                # Aggregated benchmark results
|       `-- tf_workspace/           # Terraform validation workspace
`-- unrelated/                      # Standalone helper scripts not used by main.py
```

Ignored local folders and files include `.venv/`, `__pycache__/`, `*.pyc`, and `.env`.

## Runtime Flow

1. `main.py` loads environment variables and `rules.yaml`.
2. The agent waits for `ingestion_complete` on Redis unless `SKIP_REDIS_TRIGGER=1`.
3. Phase 1 reads Neon/Postgres data and produces EC2 and S3 findings.
4. Phase 2 applies relationship guardrails to EC2 findings and emits Agent 2 decisions.
5. Phase 3 converts EC2 Phase 1 + Phase 2 results, plus S3 Phase 1 results, into LLM benchmark scenarios.
6. Outputs are printed and written as `phase1_output.json`, `phase2_output.json`, and `phase3_output.json`.

## Phase Responsibilities

Phase 1 owns detection evidence: resource identity, role, waste type, metrics, sizing recommendations, savings, and detection reasons. Its EC2 field names are close to the database shape, for example `resource_name` and `current_instance_type`.

Phase 2 owns the final Agent 2 decision after guardrails. `Phase2Result` uses Phase 3-compatible public names where equivalents exist: `instance_name`, `instance_type`, `action`, `blast_radius`, and `block_reason`. Phase 2-only fields such as `phase2_action_reason`, `phase2_decision_details`, `relationship_count`, and `skip_write` remain unchanged.

Phase 3 owns scenario shaping. `converter.py` maps Phase 1 evidence and Phase 2 decisions into the benchmark schema expected by `prompts/prompt_builder.py`.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

For the embedded benchmark:

```powershell
cd llm_benchmarking\IaC-Evaluation-Pipeline
pip install -r requirements.txt
cd tf_workspace
terraform init
```

The benchmark also expects Terraform, OPA, Checkov, and provider API keys when those validators or runners are used.

## Configuration

Create a local `.env` file for secrets and runtime settings:

```text
NEON_DATABASE_URL=postgresql://...
REDIS_URL=redis://localhost:6379
RULES_PATH=rules.yaml
SKIP_REDIS_TRIGGER=1
PHASE3_MODEL=qwen3-coder-32b
GROQ_API_KEY=...
GOOGLE_API_KEY=...
MISTRAL_API_KEY=...
```

`NEON_DATABASE_URL` is required for `main.py`. `REDIS_URL` defaults to `redis://localhost:6379`, and `RULES_PATH` defaults to `rules.yaml`.

## Commands

```powershell
python -m unittest discover -s tests
python main.py
```

Run a focused benchmark from the embedded project directory:

```powershell
python pipeline.py --models qwen3-coder-32b --scenario A1
python scorer.py
```

## Development Notes

Keep root agent changes separate from benchmark changes when possible. Add tests under `tests/` for converter behavior, guardrail changes, scenario shape changes, and any field-name compatibility changes. Do not commit `.env`, provider keys, database URLs, Redis URLs, or temporary runtime outputs unless they are intentionally reviewed artifacts.

## Output Persistence

Each run is tracked in `optimization_runs`. Phase 1 EC2/S3 outputs are saved in `phase1_ec2_outputs` and `phase1_s3_outputs`; Phase 2 EC2 guardrail output is saved in `phase2_ec2_outputs`. Phase 3 LLM output is saved separately into `waste` for EC2 and `s3_waste` for S3. See `docs/output_persistence.md`.
