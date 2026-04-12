-- Add missing relationship types required by Phase 2 guardrail logic
ALTER TYPE relationship_type_enum ADD VALUE IF NOT EXISTS 'mounted_to';
ALTER TYPE relationship_type_enum ADD VALUE IF NOT EXISTS 'routes_traffic_to';
ALTER TYPE relationship_type_enum ADD VALUE IF NOT EXISTS 'load_balances_to';
ALTER TYPE relationship_type_enum ADD VALUE IF NOT EXISTS 'sends_messages_to';
ALTER TYPE relationship_type_enum ADD VALUE IF NOT EXISTS 'reads_from_queue';
ALTER TYPE relationship_type_enum ADD VALUE IF NOT EXISTS 'monitored_by';