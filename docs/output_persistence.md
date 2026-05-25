# Output Persistence Schema

The pipeline separates raw traceability data from Phase 3 LLM recommendations.

## Run Tracking

`optimization_runs` is the parent table for one pipeline execution.

Key fields:

- `workspace_key`: optional workspace/source identifier from the trigger or environment.
- `trigger_context`: Redis trigger fields or run context as JSON.
- `phase3_model_key`: selected LLM model key.
- `status`: current multi-worker progress or terminal result.
- `error_message`: safe bounded failure context when available.
- `started_at`, `completed_at`: run timing.

Expected containerized status progression:

```text
running_phase1 -> running_phase2 -> waiting_phase3 -> running_phase3 -> completed
```

Terminal failure statuses are:

- `failed`: deterministic Agent1 processing failed.
- `phase3_failed`: Agent2 processing failed.

`start_optimization_run` retains its initial compatibility value until Agent1
updates the newly created row to `running_phase1`.

## Phase 1 Trace Tables

Phase 1 output is stored for audit and test-case reconstruction.

- `phase1_ec2_outputs`: EC2 detection output from `Phase1Result`.
- `phase1_s3_outputs`: S3 detection output from `S3FindingResult`.

Both tables store searchable columns plus `metrics` JSONB, full `raw_output` JSONB, and `run_id`.

## Phase 2 Trace Table

`phase2_ec2_outputs` stores deterministic Phase 2 guardrail decisions produced
by Agent1 for EC2 only.

It includes `phase1_action`, final `action`, `phase2_action_changed`, `phase2_action_reason`, `phase2_decision_details`, `blast_radius`, `relationship_count`, `block_reason`, and full `raw_output`.

Phase 2 does not generate S3 decisions in the current code path.

## Phase 3 LLM Output Tables

The existing tables are now Phase 3 output tables only:

- `waste`: EC2 LLM verdicts and Terraform recommendations.
- `s3_waste`: S3 LLM verdicts and Terraform recommendations.

Runtime schema setup removes outdated uniqueness assumptions on `resource_id`
and `waste_type` so multiple runs can be recorded for the same resource.

New LLM-focused columns include `run_id`, `verdict`, `decision_action`, `decided_by`, `decision_rationale`, `technical_explanation`, `cost_report`, `risk_assessment`, `terraform_action`, `terraform_block`, `llm_raw_output`, `parse_error`, and `scenario_json`.

## Worker Read/Write Boundary

- Agent1 writes Phase 1 and Phase 2 trace rows and then leaves the run in `waiting_phase3`.
- Agent2 receives only `run_id` through Redis, loads Phase 1/Phase 2 rows by `run_id`, and writes Phase 3 output rows.
- Redis is an event/metadata transport; it is not the persistence store for result payloads.

## Schema Management

The current persistence implementation ensures missing output tables and
compatible Phase 3 columns at runtime for prototype/development runs. There is
no checked-in migration script in this workspace; production deployments
should manage equivalent schema changes through the deployment database
migration process.
