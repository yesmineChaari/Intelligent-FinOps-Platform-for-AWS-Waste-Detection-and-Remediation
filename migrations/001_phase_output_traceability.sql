CREATE TABLE IF NOT EXISTS optimization_runs (
    id BIGSERIAL PRIMARY KEY,
    workspace_key TEXT,
    trigger_context JSONB,
    phase3_model_key TEXT,
    terraform_snapshot_id BIGINT,
    status TEXT NOT NULL DEFAULT 'running',
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS phase1_ec2_outputs (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT REFERENCES optimization_runs(id) ON DELETE CASCADE,
    resource_id INTEGER REFERENCES resources(id) ON DELETE SET NULL,
    resource_name TEXT,
    role TEXT,
    action TEXT NOT NULL,
    waste_type TEXT NOT NULL,
    detection_window_days INTEGER,
    stopped_days INTEGER,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    current_instance_type TEXT,
    recommended_type TEXT,
    projected_cpu_pct DOUBLE PRECISION,
    projected_ram_pct DOUBLE PRECISION,
    current_cost_per_hour NUMERIC(10, 5),
    recommended_cost_per_hour NUMERIC(10, 5),
    waste_per_month NUMERIC(12, 5),
    detection_reason TEXT,
    raw_output JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS phase1_ec2_outputs_run_idx ON phase1_ec2_outputs(run_id);
CREATE INDEX IF NOT EXISTS phase1_ec2_outputs_resource_idx ON phase1_ec2_outputs(resource_id);

CREATE TABLE IF NOT EXISTS phase1_s3_outputs (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT REFERENCES optimization_runs(id) ON DELETE CASCADE,
    resource_id INTEGER REFERENCES resources(id) ON DELETE SET NULL,
    bucket_name TEXT NOT NULL,
    grouping_key TEXT NOT NULL DEFAULT 'ALL',
    action TEXT NOT NULL,
    waste_type TEXT NOT NULL,
    detection_window TEXT,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    recommended_action TEXT,
    lifecycle_policy_json JSONB,
    detection_reason TEXT,
    raw_output JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS phase1_s3_outputs_run_idx ON phase1_s3_outputs(run_id);
CREATE INDEX IF NOT EXISTS phase1_s3_outputs_resource_idx ON phase1_s3_outputs(resource_id);

CREATE TABLE IF NOT EXISTS phase2_ec2_outputs (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT REFERENCES optimization_runs(id) ON DELETE CASCADE,
    resource_id INTEGER REFERENCES resources(id) ON DELETE SET NULL,
    instance_name TEXT,
    role TEXT,
    waste_type TEXT NOT NULL,
    phase1_action TEXT NOT NULL,
    action TEXT NOT NULL,
    phase2_action_changed BOOLEAN NOT NULL DEFAULT FALSE,
    phase2_action_reason TEXT,
    phase2_decision_details TEXT,
    blast_radius_explanation TEXT,
    blast_radius INTEGER NOT NULL DEFAULT 0,
    relationship_count INTEGER NOT NULL DEFAULT 0,
    skip_write BOOLEAN NOT NULL DEFAULT FALSE,
    block_reason TEXT,
    detection_window_days INTEGER,
    stopped_days INTEGER,
    instance_type TEXT,
    recommended_type TEXT,
    current_cost_per_hour NUMERIC(10, 5),
    recommended_cost_per_hour NUMERIC(10, 5),
    waste_per_month NUMERIC(12, 5),
    detection_reason TEXT,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_output JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS phase2_ec2_outputs_run_idx ON phase2_ec2_outputs(run_id);
CREATE INDEX IF NOT EXISTS phase2_ec2_outputs_resource_idx ON phase2_ec2_outputs(resource_id);

CREATE TABLE IF NOT EXISTS waste (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT REFERENCES optimization_runs(id) ON DELETE SET NULL,
    resource_id INTEGER REFERENCES resources(id) ON DELETE CASCADE,
    waste_type TEXT NOT NULL,
    action TEXT DEFAULT 'PENDING' NOT NULL
);

ALTER TABLE waste DROP CONSTRAINT IF EXISTS waste_resource_id_key;
ALTER TABLE waste DROP CONSTRAINT IF EXISTS waste_waste_type_key;
ALTER TABLE waste DROP CONSTRAINT IF EXISTS unique_active_waste;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'waste'
          AND column_name = 'detection_window'
    ) THEN
        ALTER TABLE waste ALTER COLUMN detection_window DROP NOT NULL;
    END IF;
END $$;

ALTER TABLE waste ADD COLUMN IF NOT EXISTS run_id BIGINT REFERENCES optimization_runs(id) ON DELETE SET NULL;
ALTER TABLE waste ADD COLUMN IF NOT EXISTS verdict TEXT;
ALTER TABLE waste ADD COLUMN IF NOT EXISTS decision_action TEXT;
ALTER TABLE waste ADD COLUMN IF NOT EXISTS decided_by TEXT;
ALTER TABLE waste ADD COLUMN IF NOT EXISTS decision_rationale TEXT;
ALTER TABLE waste ADD COLUMN IF NOT EXISTS technical_explanation TEXT;
ALTER TABLE waste ADD COLUMN IF NOT EXISTS cost_report JSONB;
ALTER TABLE waste ADD COLUMN IF NOT EXISTS risk_assessment JSONB;
ALTER TABLE waste ADD COLUMN IF NOT EXISTS pipeline_warning_acknowledged BOOLEAN;
ALTER TABLE waste ADD COLUMN IF NOT EXISTS data_loss_acknowledged BOOLEAN;
ALTER TABLE waste ADD COLUMN IF NOT EXISTS terraform_action TEXT;
ALTER TABLE waste ADD COLUMN IF NOT EXISTS terraform_block TEXT;
ALTER TABLE waste ADD COLUMN IF NOT EXISTS llm_raw_output JSONB;
ALTER TABLE waste ADD COLUMN IF NOT EXISTS parse_error TEXT;
ALTER TABLE waste ADD COLUMN IF NOT EXISTS scenario_json JSONB;
ALTER TABLE waste ADD COLUMN IF NOT EXISTS phase3_created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS waste_run_idx ON waste(run_id);
CREATE INDEX IF NOT EXISTS waste_resource_run_idx ON waste(resource_id, run_id);

CREATE TABLE IF NOT EXISTS s3_waste (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT REFERENCES optimization_runs(id) ON DELETE SET NULL,
    resource_id INTEGER REFERENCES resources(id) ON DELETE CASCADE,
    bucket_name TEXT,
    grouping_key TEXT NOT NULL DEFAULT 'ALL',
    waste_type TEXT NOT NULL,
    action TEXT DEFAULT 'PENDING' NOT NULL
);

ALTER TABLE s3_waste DROP CONSTRAINT IF EXISTS s3_waste_resource_id_key;
ALTER TABLE s3_waste DROP CONSTRAINT IF EXISTS s3_waste_waste_type_key;
ALTER TABLE s3_waste DROP CONSTRAINT IF EXISTS unique_s3_waste;
ALTER TABLE s3_waste ALTER COLUMN resource_id DROP NOT NULL;

ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS run_id BIGINT REFERENCES optimization_runs(id) ON DELETE SET NULL;
ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS bucket_name TEXT;
ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS grouping_key TEXT NOT NULL DEFAULT 'ALL';
ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS verdict TEXT;
ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS decision_action TEXT;
ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS decided_by TEXT;
ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS decision_rationale TEXT;
ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS technical_explanation TEXT;
ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS cost_report JSONB;
ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS risk_assessment JSONB;
ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS pipeline_warning_acknowledged BOOLEAN;
ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS data_loss_acknowledged BOOLEAN;
ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS terraform_action TEXT;
ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS terraform_block TEXT;
ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS llm_raw_output JSONB;
ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS parse_error TEXT;
ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS scenario_json JSONB;
ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS phase3_created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS s3_waste_run_idx ON s3_waste(run_id);
CREATE INDEX IF NOT EXISTS s3_waste_resource_run_idx ON s3_waste(resource_id, run_id);
