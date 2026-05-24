# Output Persistence Schema

The pipeline separates raw traceability data from Phase 3 LLM recommendations.

## Run Tracking

`optimization_runs` is the parent table for one pipeline execution.

Key fields:

- `workspace_key`: optional workspace/source identifier from the trigger or environment.
- `trigger_context`: Redis trigger fields or run context as JSON.
- `phase3_model_key`: selected LLM model key.
- `status`: `running`, `completed`, or `failed`.
- `started_at`, `completed_at`: run timing.

## Phase 1 Trace Tables

Phase 1 output is stored for audit and test-case reconstruction.

- `phase1_ec2_outputs`: EC2 detection output from `Phase1Result`.
- `phase1_s3_outputs`: S3 detection output from `S3FindingResult`.

Both tables store searchable columns plus `metrics` JSONB, full `raw_output` JSONB, and `run_id`.

## Phase 2 Trace Table

`phase2_ec2_outputs` stores Agent 2 guardrail decisions for EC2 only.

It includes `phase1_action`, final `action`, `phase2_action_changed`, `phase2_action_reason`, `phase2_decision_details`, `blast_radius`, `relationship_count`, `block_reason`, and full `raw_output`.

Phase 2 does not generate S3 decisions in the current code path.

## Phase 3 LLM Output Tables

The existing tables are now Phase 3 output tables only:

- `waste`: EC2 LLM verdicts and Terraform recommendations.
- `s3_waste`: S3 LLM verdicts and Terraform recommendations.

The migration removes outdated uniqueness assumptions on `resource_id` and `waste_type` so multiple runs can be recorded for the same resource.

New LLM-focused columns include `run_id`, `verdict`, `decision_action`, `decided_by`, `decision_rationale`, `technical_explanation`, `cost_report`, `risk_assessment`, `terraform_action`, `terraform_block`, `llm_raw_output`, `parse_error`, and `scenario_json`.

## Migration

Apply:

```sql
migrations/001_phase_output_traceability.sql
```

The application also creates missing trace tables at runtime for prototype runs, but the migration should be applied to Neon for a stable schema.
