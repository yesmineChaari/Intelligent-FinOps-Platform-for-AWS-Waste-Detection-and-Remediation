from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable

import asyncpg


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _json(value: Any) -> str:
    return json.dumps(value, default=_json_default)


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    if isinstance(model, dict):
        return dict(model)
    return dict(getattr(model, "__dict__", {}))


def _phase1_ec2_metrics(result: Any) -> dict[str, Any]:
    fields = (
        "p95_cpu",
        "p99_cpu",
        "max_cpu",
        "p95_ram",
        "cv",
        "p99_network_mbps",
        "p99_disk_mbps",
        "max_network_mbps",
        "max_disk_mbps",
        "stopped_days",
    )
    return {field: getattr(result, field) for field in fields if getattr(result, field, None) is not None}


def _phase1_s3_metrics(result: Any) -> dict[str, Any]:
    fields = (
        "has_lifecycle",
        "total_requests_30d",
        "object_count",
        "pct_older_90_days",
        "estimated_monthly_savings",
    )
    return {field: getattr(result, field) for field in fields if getattr(result, field, None) is not None}


def _phase2_metrics(result: Any) -> dict[str, Any]:
    fields = ("blast_radius", "relationship_count", "phase2_action_changed", "stopped_days")
    return {field: getattr(result, field) for field in fields if getattr(result, field, None) is not None}


async def ensure_output_tables(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
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
        )
        """
    )
    await conn.execute(
        """
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
        )
        """
    )
    await conn.execute("CREATE INDEX IF NOT EXISTS phase1_ec2_outputs_run_idx ON phase1_ec2_outputs(run_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS phase1_ec2_outputs_resource_idx ON phase1_ec2_outputs(resource_id)")
    await conn.execute(
        """
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
        )
        """
    )
    await conn.execute("CREATE INDEX IF NOT EXISTS phase1_s3_outputs_run_idx ON phase1_s3_outputs(run_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS phase1_s3_outputs_resource_idx ON phase1_s3_outputs(resource_id)")
    await conn.execute(
        """
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
        )
        """
    )
    await conn.execute("CREATE INDEX IF NOT EXISTS phase2_ec2_outputs_run_idx ON phase2_ec2_outputs(run_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS phase2_ec2_outputs_resource_idx ON phase2_ec2_outputs(resource_id)")
    await _ensure_phase3_tables(conn)


async def _ensure_phase3_tables(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS waste (
            id BIGSERIAL PRIMARY KEY,
            run_id BIGINT REFERENCES optimization_runs(id) ON DELETE SET NULL,
            resource_id INTEGER REFERENCES resources(id) ON DELETE CASCADE,
            waste_type TEXT NOT NULL,
            action TEXT DEFAULT 'PENDING' NOT NULL
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS s3_waste (
            id BIGSERIAL PRIMARY KEY,
            run_id BIGINT REFERENCES optimization_runs(id) ON DELETE SET NULL,
            resource_id INTEGER REFERENCES resources(id) ON DELETE CASCADE,
            bucket_name TEXT,
            grouping_key TEXT NOT NULL DEFAULT 'ALL',
            waste_type TEXT NOT NULL,
            action TEXT DEFAULT 'PENDING' NOT NULL
        )
        """
    )

    statements = [
        "ALTER TABLE waste DROP CONSTRAINT IF EXISTS waste_resource_id_key",
        "ALTER TABLE waste DROP CONSTRAINT IF EXISTS waste_waste_type_key",
        "ALTER TABLE waste DROP CONSTRAINT IF EXISTS unique_active_waste",
        "ALTER TABLE waste ALTER COLUMN detection_window DROP NOT NULL",
        "ALTER TABLE waste ADD COLUMN IF NOT EXISTS run_id BIGINT REFERENCES optimization_runs(id) ON DELETE SET NULL",
        "ALTER TABLE waste ADD COLUMN IF NOT EXISTS verdict TEXT",
        "ALTER TABLE waste ADD COLUMN IF NOT EXISTS decision_action TEXT",
        "ALTER TABLE waste ADD COLUMN IF NOT EXISTS decided_by TEXT",
        "ALTER TABLE waste ADD COLUMN IF NOT EXISTS decision_rationale TEXT",
        "ALTER TABLE waste ADD COLUMN IF NOT EXISTS technical_explanation TEXT",
        "ALTER TABLE waste ADD COLUMN IF NOT EXISTS cost_report JSONB",
        "ALTER TABLE waste ADD COLUMN IF NOT EXISTS risk_assessment JSONB",
        "ALTER TABLE waste ADD COLUMN IF NOT EXISTS pipeline_warning_acknowledged BOOLEAN",
        "ALTER TABLE waste ADD COLUMN IF NOT EXISTS data_loss_acknowledged BOOLEAN",
        "ALTER TABLE waste ADD COLUMN IF NOT EXISTS terraform_action TEXT",
        "ALTER TABLE waste ADD COLUMN IF NOT EXISTS terraform_block TEXT",
        "ALTER TABLE waste ADD COLUMN IF NOT EXISTS llm_raw_output JSONB",
        "ALTER TABLE waste ADD COLUMN IF NOT EXISTS parse_error TEXT",
        "ALTER TABLE waste ADD COLUMN IF NOT EXISTS scenario_json JSONB",
        "ALTER TABLE waste ADD COLUMN IF NOT EXISTS phase3_created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
        "CREATE INDEX IF NOT EXISTS waste_run_idx ON waste(run_id)",
        "CREATE INDEX IF NOT EXISTS waste_resource_run_idx ON waste(resource_id, run_id)",
        "ALTER TABLE s3_waste DROP CONSTRAINT IF EXISTS s3_waste_resource_id_key",
        "ALTER TABLE s3_waste DROP CONSTRAINT IF EXISTS s3_waste_waste_type_key",
        "ALTER TABLE s3_waste DROP CONSTRAINT IF EXISTS unique_s3_waste",
        "ALTER TABLE s3_waste ALTER COLUMN resource_id DROP NOT NULL",
        "ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS run_id BIGINT REFERENCES optimization_runs(id) ON DELETE SET NULL",
        "ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS bucket_name TEXT",
        "ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS grouping_key TEXT NOT NULL DEFAULT 'ALL'",
        "ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS verdict TEXT",
        "ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS decision_action TEXT",
        "ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS decided_by TEXT",
        "ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS decision_rationale TEXT",
        "ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS technical_explanation TEXT",
        "ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS cost_report JSONB",
        "ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS risk_assessment JSONB",
        "ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS pipeline_warning_acknowledged BOOLEAN",
        "ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS data_loss_acknowledged BOOLEAN",
        "ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS terraform_action TEXT",
        "ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS terraform_block TEXT",
        "ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS llm_raw_output JSONB",
        "ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS parse_error TEXT",
        "ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS scenario_json JSONB",
        "ALTER TABLE s3_waste ADD COLUMN IF NOT EXISTS phase3_created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
        "CREATE INDEX IF NOT EXISTS s3_waste_run_idx ON s3_waste(run_id)",
        "CREATE INDEX IF NOT EXISTS s3_waste_resource_run_idx ON s3_waste(resource_id, run_id)",
    ]
    for statement in statements:
        try:
            await conn.execute(statement)
        except asyncpg.UndefinedColumnError:
            # Minimal test/dev schemas may not have legacy columns such as detection_window.
            continue


async def start_optimization_run(
    conn: asyncpg.Connection,
    *,
    workspace_key: str | None = None,
    trigger_context: dict[str, Any] | None = None,
    phase3_model_key: str | None = None,
    terraform_snapshot_id: int | None = None,
) -> int:
    await ensure_output_tables(conn)
    row = await conn.fetchrow(
        """
        INSERT INTO optimization_runs (
            workspace_key,
            trigger_context,
            phase3_model_key,
            terraform_snapshot_id,
            status
        )
        VALUES ($1, $2::jsonb, $3, $4, 'running')
        RETURNING id
        """,
        workspace_key,
        _json(trigger_context or {}),
        phase3_model_key,
        terraform_snapshot_id,
    )
    return int(row["id"])


async def complete_optimization_run(
    conn: asyncpg.Connection,
    run_id: int,
    *,
    status: str = "completed",
    error_message: str | None = None,
    terraform_snapshot_id: int | None = None,
) -> None:
    await conn.execute(
        """
        UPDATE optimization_runs
        SET status = $2,
            error_message = $3,
            terraform_snapshot_id = COALESCE($4, terraform_snapshot_id),
            completed_at = NOW()
        WHERE id = $1
        """,
        run_id,
        status,
        error_message,
        terraform_snapshot_id,
    )


async def update_optimization_run_status(
    conn: asyncpg.Connection,
    run_id: int,
    status: str,
    error_message: str | None = None,
) -> None:
    try:
        await conn.execute(
            """
            UPDATE optimization_runs
            SET status = $2,
                error_message = $3
            WHERE id = $1
            """,
            run_id,
            status,
            error_message,
        )
    except asyncpg.UndefinedColumnError:
        # Legacy optimization_runs tables may predate error_message.
        await conn.execute(
            """
            UPDATE optimization_runs
            SET status = $2
            WHERE id = $1
            """,
            run_id,
            status,
        )


async def _load_s3_resource_ids(conn: asyncpg.Connection, bucket_names: Iterable[str]) -> dict[str, int]:
    names = sorted({name for name in bucket_names if name})
    if not names:
        return {}
    rows = await conn.fetch(
        """
        SELECT name, resource_id
        FROM s3_instances
        WHERE name = ANY($1::text[])
        """,
        names,
    )
    return {str(row["name"]): int(row["resource_id"]) for row in rows}


async def save_phase1_outputs(
    conn: asyncpg.Connection,
    run_id: int,
    ec2_results: list[Any],
    s3_results: list[Any],
) -> None:
    await ensure_output_tables(conn)
    ec2_rows = []
    for result in ec2_results:
        ec2_rows.append(
            (
                run_id,
                getattr(result, "resource_id", None),
                getattr(result, "resource_name", None),
                getattr(result, "role", None),
                _enum_value(getattr(result, "action", None)),
                _enum_value(getattr(result, "waste_type", None)),
                getattr(result, "detection_window_days", None),
                getattr(result, "stopped_days", None),
                _json(_phase1_ec2_metrics(result)),
                getattr(result, "current_instance_type", None),
                getattr(result, "recommended_type", None),
                getattr(result, "projected_cpu_pct", None),
                getattr(result, "projected_ram_pct", None),
                getattr(result, "current_cost_per_hour", None),
                getattr(result, "recommended_cost_per_hour", None),
                getattr(result, "waste_per_month", None),
                getattr(result, "detection_reason", None),
                _json(_model_dump(result)),
            )
        )
    if ec2_rows:
        await conn.executemany(
            """
            INSERT INTO phase1_ec2_outputs (
                run_id, resource_id, resource_name, role, action, waste_type,
                detection_window_days, stopped_days, metrics, current_instance_type,
                recommended_type, projected_cpu_pct, projected_ram_pct,
                current_cost_per_hour, recommended_cost_per_hour, waste_per_month,
                detection_reason, raw_output
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11, $12,
                $13, $14, $15, $16, $17, $18::jsonb
            )
            """,
            ec2_rows,
        )

    s3_resource_ids = await _load_s3_resource_ids(conn, [getattr(r, "bucket_name", "") for r in s3_results])
    s3_rows = []
    for result in s3_results:
        bucket_name = getattr(result, "bucket_name", None)
        s3_rows.append(
            (
                run_id,
                s3_resource_ids.get(bucket_name),
                bucket_name,
                getattr(result, "grouping_key", "ALL"),
                _enum_value(getattr(result, "action", None)),
                _enum_value(getattr(result, "waste_type", None)),
                getattr(result, "detection_window", None),
                _json(_phase1_s3_metrics(result)),
                getattr(result, "recommended_action", None),
                _json(getattr(result, "lifecycle_policy_json", None)),
                getattr(result, "detection_reason", None),
                _json(_model_dump(result)),
            )
        )
    if s3_rows:
        await conn.executemany(
            """
            INSERT INTO phase1_s3_outputs (
                run_id, resource_id, bucket_name, grouping_key, action, waste_type,
                detection_window, metrics, recommended_action, lifecycle_policy_json,
                detection_reason, raw_output
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10::jsonb, $11, $12::jsonb)
            """,
            s3_rows,
        )


async def save_phase2_outputs(conn: asyncpg.Connection, run_id: int, phase2_results: list[Any]) -> None:
    await ensure_output_tables(conn)
    rows = []
    for result in phase2_results:
        rows.append(
            (
                run_id,
                getattr(result, "resource_id", None),
                getattr(result, "instance_name", getattr(result, "resource_name", None)),
                getattr(result, "role", None),
                _enum_value(getattr(result, "waste_type", None)),
                _enum_value(getattr(result, "phase1_action", None)),
                _enum_value(getattr(result, "action", getattr(result, "phase2_action", None))),
                getattr(result, "phase2_action_changed", False),
                getattr(result, "phase2_action_reason", None),
                getattr(result, "phase2_decision_details", None),
                getattr(result, "blast_radius_explanation", None),
                getattr(result, "blast_radius", getattr(result, "blast_radius_score", 0)),
                getattr(result, "relationship_count", 0),
                getattr(result, "skip_write", False),
                getattr(result, "block_reason", getattr(result, "guardrail_reason", None)),
                getattr(result, "detection_window_days", None),
                getattr(result, "stopped_days", None),
                getattr(result, "instance_type", getattr(result, "current_instance_type", None)),
                getattr(result, "recommended_type", None),
                getattr(result, "current_cost_per_hour", None),
                getattr(result, "recommended_cost_per_hour", None),
                getattr(result, "waste_per_month", None),
                getattr(result, "detection_reason", None),
                _json(_phase2_metrics(result)),
                _json(_model_dump(result)),
            )
        )
    if rows:
        await conn.executemany(
            """
            INSERT INTO phase2_ec2_outputs (
                run_id, resource_id, instance_name, role, waste_type,
                phase1_action, action, phase2_action_changed, phase2_action_reason,
                phase2_decision_details, blast_radius_explanation, blast_radius,
                relationship_count, skip_write, block_reason, detection_window_days,
                stopped_days, instance_type, recommended_type, current_cost_per_hour,
                recommended_cost_per_hour, waste_per_month, detection_reason, metrics, raw_output
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                $14, $15, $16, $17, $18, $19, $20, $21, $22, $23,
                $24::jsonb, $25::jsonb
            )
            """,
            rows,
        )


def _merge_raw_output(record: Any) -> dict[str, Any]:
    row = dict(record)
    raw = row.get("raw_output")
    if isinstance(raw, dict):
        merged = dict(raw)
        merged.update(row)
        return merged
    return row


async def load_phase1_ec2_outputs(conn: asyncpg.Connection, run_id: int) -> list[dict[str, Any]]:
    records = await conn.fetch(
        """
        SELECT *
        FROM phase1_ec2_outputs
        WHERE run_id = $1
        ORDER BY id
        """,
        run_id,
    )
    return [_merge_raw_output(record) for record in records]


async def load_phase1_s3_outputs(conn: asyncpg.Connection, run_id: int) -> list[dict[str, Any]]:
    records = await conn.fetch(
        """
        SELECT *
        FROM phase1_s3_outputs
        WHERE run_id = $1
        ORDER BY id
        """,
        run_id,
    )
    return [_merge_raw_output(record) for record in records]


async def load_phase2_ec2_outputs(conn: asyncpg.Connection, run_id: int) -> list[dict[str, Any]]:
    records = await conn.fetch(
        """
        SELECT *
        FROM phase2_ec2_outputs
        WHERE run_id = $1
        ORDER BY id
        """,
        run_id,
    )
    return [_merge_raw_output(record) for record in records]


def _phase3_resource_maps(phase2_results: list[Any], s3_results: list[Any]) -> tuple[dict[str, int], dict[str, str]]:
    ec2_by_name: dict[str, int] = {}
    ec2_waste_type_by_name: dict[str, str] = {}
    for result in phase2_results:
        if isinstance(result, dict):
            name = result.get("instance_name") or result.get("resource_name")
            resource_id = result.get("resource_id")
            waste_type = result.get("waste_type", "none")
        else:
            name = getattr(result, "instance_name", getattr(result, "resource_name", None))
            resource_id = getattr(result, "resource_id", None)
            waste_type = getattr(result, "waste_type", "none")
        if not name:
            continue
        if resource_id is None:
            continue
        ec2_by_name[str(name)] = int(resource_id)
        ec2_waste_type_by_name[str(name)] = str(_enum_value(waste_type))
    return ec2_by_name, ec2_waste_type_by_name


def _single_or_none(value: Any) -> Any:
    return value if value not in ("", [], {}) else None


def _parsed_decision(parsed: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        return {}
    decision = parsed.get("decision_summary")
    return decision if isinstance(decision, dict) else {}


def _phase3_common(parsed: dict[str, Any] | None, llm: dict[str, Any]) -> dict[str, Any]:
    parsed = parsed if isinstance(parsed, dict) else {}
    decision = _parsed_decision(parsed)
    return {
        "verdict": parsed.get("verdict"),
        "decision_action": decision.get("action"),
        "decided_by": decision.get("decided_by"),
        "decision_rationale": decision.get("rationale"),
        "technical_explanation": parsed.get("technical_explanation"),
        "cost_report": parsed.get("cost_report"),
        "risk_assessment": parsed.get("risk_assessment"),
        "pipeline_warning_acknowledged": parsed.get("pipeline_warning_acknowledged"),
        "data_loss_acknowledged": parsed.get("data_loss_acknowledged"),
        "terraform_action": parsed.get("terraform_action"),
        "terraform_block": parsed.get("terraform_block"),
        "llm_raw_output": llm,
        "parse_error": llm.get("parse_error") if isinstance(llm, dict) else None,
    }


async def save_phase3_outputs(
    conn: asyncpg.Connection,
    run_id: int,
    phase3_output: dict[str, Any],
    *,
    phase2_results: list[Any],
    s3_results: list[Any],
) -> None:
    await ensure_output_tables(conn)
    ec2_by_name, ec2_waste_type_by_name = _phase3_resource_maps(phase2_results, s3_results)
    s3_resource_ids = await _load_s3_resource_ids(
        conn,
        [
            result.get("bucket_name", "") if isinstance(result, dict) else getattr(result, "bucket_name", "")
            for result in s3_results
        ],
    )

    for run in phase3_output.get("runs") or []:
        scenario_type = run.get("scenario_type")
        scenario = run.get("scenario") or {}
        llm = run.get("llm") or {}
        parsed = llm.get("parsed") if isinstance(llm, dict) else None

        if scenario_type == "ec2":
            await _save_phase3_ec2_run(
                conn,
                run_id,
                scenario,
                llm,
                parsed,
                ec2_by_name,
                ec2_waste_type_by_name,
            )
        elif scenario_type == "s3":
            await _save_phase3_s3_run(conn, run_id, scenario, llm, parsed, s3_resource_ids)


async def _save_phase3_ec2_run(
    conn: asyncpg.Connection,
    run_id: int,
    scenario: dict[str, Any],
    llm: dict[str, Any],
    parsed: dict[str, Any] | None,
    ec2_by_name: dict[str, int],
    ec2_waste_type_by_name: dict[str, str],
) -> None:
    resources = scenario.get("flagged_resources") or []
    common = _phase3_common(parsed, llm)
    instances = parsed.get("instances") if isinstance(parsed, dict) else None
    rows = []
    for resource in resources:
        name = str(resource.get("instance_name") or resource.get("instance_id") or "")
        resource_id = ec2_by_name.get(name)
        if resource_id is None:
            continue
        resource_parsed = instances.get(resource.get("instance_id")) if isinstance(instances, dict) else parsed
        resource_common = _phase3_common(resource_parsed, llm)
        if not resource_common["verdict"]:
            resource_common = common
        rows.append(
            (
                run_id,
                resource_id,
                ec2_waste_type_by_name.get(name, "none"),
                resource_common.get("decision_action") or resource.get("agent2_decision", {}).get("action") or "PENDING",
                resource_common.get("verdict"),
                resource_common.get("decision_action"),
                resource_common.get("decided_by"),
                resource_common.get("decision_rationale"),
                resource_common.get("technical_explanation"),
                _json(resource_common.get("cost_report")),
                _json(resource_common.get("risk_assessment")),
                resource_common.get("pipeline_warning_acknowledged"),
                resource_common.get("data_loss_acknowledged"),
                resource_common.get("terraform_action"),
                resource_common.get("terraform_block"),
                _json(resource_common.get("llm_raw_output")),
                resource_common.get("parse_error"),
                _json(scenario),
            )
        )
    if rows:
        await conn.executemany(
            """
            INSERT INTO waste (
                run_id, resource_id, waste_type, action, verdict, decision_action,
                decided_by, decision_rationale, technical_explanation, cost_report,
                risk_assessment, pipeline_warning_acknowledged, data_loss_acknowledged,
                terraform_action, terraform_block, llm_raw_output, parse_error, scenario_json
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11::jsonb,
                $12, $13, $14, $15, $16::jsonb, $17, $18::jsonb
            )
            """,
            rows,
        )


async def _save_phase3_s3_run(
    conn: asyncpg.Connection,
    run_id: int,
    scenario: dict[str, Any],
    llm: dict[str, Any],
    parsed: dict[str, Any] | None,
    s3_resource_ids: dict[str, int],
) -> None:
    common = _phase3_common(parsed, llm)
    rows = []
    scenario_findings = scenario.get("findings")
    if isinstance(scenario_findings, list):
        items = scenario_findings
    else:
        items = [{"finding": scenario.get("finding") or {}, "agent2_decision": scenario.get("agent2_decision") or {}}]

    parsed_findings = parsed.get("findings") if isinstance(parsed, dict) else None
    for item in items:
        finding = item.get("finding") or {}
        bucket_name = finding.get("bucket_name")
        if not bucket_name:
            continue
        parsed_item = parsed_findings.get(item.get("resource_id")) if isinstance(parsed_findings, dict) else parsed
        item_common = _phase3_common(parsed_item, llm)
        if not item_common["verdict"]:
            item_common = common
        rows.append(
            (
                run_id,
                s3_resource_ids.get(bucket_name),
                bucket_name,
                finding.get("grouping_key") or "ALL",
                finding.get("finding_type") or "s3_optimization",
                item.get("agent2_decision", {}).get("action") or item_common.get("decision_action") or "PENDING",
                item_common.get("verdict"),
                item_common.get("decision_action"),
                item_common.get("decided_by"),
                item_common.get("decision_rationale"),
                item_common.get("technical_explanation"),
                _json(item_common.get("cost_report")),
                _json(item_common.get("risk_assessment")),
                item_common.get("pipeline_warning_acknowledged"),
                item_common.get("data_loss_acknowledged"),
                item_common.get("terraform_action"),
                item_common.get("terraform_block"),
                _json(item_common.get("llm_raw_output")),
                item_common.get("parse_error"),
                _json(scenario),
            )
        )
    if rows:
        await conn.executemany(
            """
            INSERT INTO s3_waste (
                run_id, resource_id, bucket_name, grouping_key, waste_type, action, verdict,
                decision_action, decided_by, decision_rationale, technical_explanation,
                cost_report, risk_assessment, pipeline_warning_acknowledged,
                data_loss_acknowledged, terraform_action, terraform_block,
                llm_raw_output, parse_error, scenario_json
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                $12::jsonb, $13::jsonb, $14, $15, $16, $17, $18::jsonb,
                $19, $20::jsonb
            )
            """,
            rows,
        )
