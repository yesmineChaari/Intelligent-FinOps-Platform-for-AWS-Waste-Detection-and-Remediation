"""Read-only dashboard queries over persisted pipeline and inventory tables."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from app.db import read_connection
from app.schemas.alerts import AlertResponse
from app.schemas.ec2 import Ec2FindingResponse
from app.schemas.guardrails import GuardrailDecisionResponse
from app.schemas.overview import (
    FindingTypeCountResponse,
    LatestRunSummaryResponse,
    OverviewResponse,
    SavingsTrendPointResponse,
)
from app.schemas.phase3 import Phase3ReviewResponse
from app.schemas.runs import RunResponse
from app.schemas.s3 import S3FindingResponse


UNAVAILABLE = "Unavailable"


def _float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _text(value: object, default: str = UNAVAILABLE) -> str:
    text = str(value).strip() if value is not None else ""
    return text or default


def _percent(value: object) -> str:
    if value is None:
        return UNAVAILABLE
    return f"{_float(value):.1f}%"


def _timestamp(value: datetime | None) -> str:
    return value.isoformat() if value is not None else UNAVAILABLE


def _sort_timestamp(value: datetime | None) -> float:
    return value.timestamp() if value is not None else float("-inf")


def _duration(started_at: datetime | None, completed_at: datetime | None) -> str:
    if started_at is None or completed_at is None:
        return UNAVAILABLE
    seconds = max(int((completed_at - started_at).total_seconds()), 0)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _action_label(action: object, recommended_type: object = None) -> str:
    normalized = _text(action, "").upper()
    recommendation = _text(recommended_type, "")
    if normalized in {"DOWNSIZE", "RESIZE"} and recommendation:
        return f"Resize to {recommendation}"
    labels = {
        "STOP": "Stop instance",
        "TERMINATE": "Terminate instance",
        "DELETE": "Delete resource",
        "CLEAN": "Apply lifecycle cleanup",
        "LIFECYCLE": "Apply lifecycle policy",
        "REVIEW": "Review manually",
        "SKIP": "No automated action",
        "KEEP": "Keep resource",
    }
    if normalized in labels:
        return labels[normalized]
    return normalized.replace("_", " ").title() if normalized else UNAVAILABLE


def _risk(action: object, blast_radius: object, block_reason: object) -> str:
    score = int(_float(blast_radius))
    normalized = _text(action, "").upper()
    if score >= 7:
        return "Critical"
    if block_reason or normalized in {"SKIP", "REVIEW"}:
        return "High"
    if score >= 3:
        return "Medium"
    return "Low"


def _finding_status(action: object, block_reason: object) -> str:
    normalized = _text(action, "").upper()
    if block_reason or normalized == "SKIP":
        return "Blocked"
    if normalized == "REVIEW":
        return "Review"
    return "Recommended"


def _footprint(object_count: object, size_bytes: object) -> str:
    components: list[str] = []
    if object_count is not None:
        components.append(f"{int(_float(object_count)):,} objects")
    if size_bytes is not None:
        components.append(f"{_float(size_bytes) / (1024 ** 3):.1f} GB")
    return " / ".join(components) or UNAVAILABLE


async def get_ec2_findings() -> list[Ec2FindingResponse]:
    query = """
        WITH latest_run AS (
            SELECT id
            FROM optimization_runs
            ORDER BY id DESC
            LIMIT 1
        )
        SELECT
            p1.resource_id,
            p1.resource_name,
            p1.waste_type,
            p1.detection_reason,
            p1.current_instance_type,
            p1.recommended_type AS p1_recommended_type,
            p1.waste_per_month AS p1_saving,
            NULLIF(p1.metrics ->> 'p95_cpu', '')::double precision AS saved_p95_cpu,
            p2.action AS final_action,
            p2.recommended_type AS p2_recommended_type,
            p2.waste_per_month AS p2_saving,
            p2.blast_radius,
            p2.block_reason,
            inventory.region,
            inventory.instance_type AS inventory_instance_type,
            telemetry.avg_cpu,
            telemetry.avg_ram,
            telemetry.p95_cpu AS telemetry_p95_cpu
        FROM phase1_ec2_outputs p1
        JOIN latest_run run ON run.id = p1.run_id
        LEFT JOIN phase2_ec2_outputs p2
          ON p2.run_id = p1.run_id
         AND (
             p2.resource_id = p1.resource_id
             OR (p2.resource_id IS NULL AND p2.instance_name = p1.resource_name)
         )
        LEFT JOIN ec2_instances inventory ON inventory.resource_id = p1.resource_id
        LEFT JOIN LATERAL (
            SELECT
                AVG(metrics.cpu_pct) FILTER (WHERE metrics.cpu_pct IS NOT NULL) AS avg_cpu,
                AVG(metrics.ram_pct) FILTER (WHERE metrics.ram_pct IS NOT NULL) AS avg_ram,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY metrics.cpu_pct)
                    FILTER (WHERE metrics.cpu_pct IS NOT NULL) AS p95_cpu
            FROM ec2_metrics metrics
            WHERE metrics.resource_id = p1.resource_id
        ) telemetry ON TRUE
        ORDER BY COALESCE(p2.waste_per_month, p1.waste_per_month, 0) DESC, p1.id
    """
    async with read_connection() as conn:
        records = await conn.fetch(query)

    findings: list[Ec2FindingResponse] = []
    for record in records:
        row = dict(record)
        action = row.get("final_action") or "REVIEW"
        recommendation_type = (
            row.get("p2_recommended_type") or row.get("p1_recommended_type")
        )
        findings.append(
            Ec2FindingResponse(
                instance=_text(row.get("resource_name")),
                region=_text(row.get("region")),
                instanceType=_text(
                    row.get("current_instance_type")
                    or row.get("inventory_instance_type")
                ),
                issue=_text(row.get("detection_reason") or row.get("waste_type")),
                cpuAverage=_percent(row.get("avg_cpu")),
                cpuP95=_percent(
                    row.get("saved_p95_cpu") or row.get("telemetry_p95_cpu")
                ),
                memoryAverage=_percent(row.get("avg_ram")),
                recommendation=_action_label(action, recommendation_type),
                estimatedSaving=_float(row.get("p2_saving") or row.get("p1_saving")),
                risk=_risk(
                    action,
                    row.get("blast_radius"),
                    row.get("block_reason"),
                ),
                status=_finding_status(action, row.get("block_reason")),
            )
        )
    return findings


async def get_s3_findings() -> list[S3FindingResponse]:
    query = """
        WITH latest_run AS (
            SELECT id
            FROM optimization_runs
            ORDER BY id DESC
            LIMIT 1
        )
        SELECT
            output.bucket_name,
            output.action,
            output.waste_type,
            output.detection_reason,
            output.recommended_action,
            NULLIF(output.metrics ->> 'object_count', '')::bigint AS saved_object_count,
            NULLIF(output.metrics ->> 'estimated_monthly_savings', '')::numeric
                AS estimated_saving,
            inventory.region,
            inventory.object_count,
            inventory.size_bytes
        FROM phase1_s3_outputs output
        JOIN latest_run run ON run.id = output.run_id
        LEFT JOIN s3_instances inventory ON inventory.resource_id = output.resource_id
        ORDER BY estimated_saving DESC NULLS LAST, output.id
    """
    async with read_connection() as conn:
        records = await conn.fetch(query)

    return [
        S3FindingResponse(
            bucket=_text(row["bucket_name"]),
            region=_text(row["region"]),
            issue=_text(row["detection_reason"] or row["waste_type"]),
            storageClass=UNAVAILABLE,
            footprint=_footprint(
                row["saved_object_count"] or row["object_count"],
                row["size_bytes"],
            ),
            lifecycleAction=_text(row["recommended_action"] or row["action"]),
            estimatedSaving=_float(row["estimated_saving"]),
            status="Recommended",
        )
        for row in (dict(record) for record in records)
    ]


async def get_guardrail_results() -> list[GuardrailDecisionResponse]:
    query = """
        WITH latest_run AS (
            SELECT id
            FROM optimization_runs
            ORDER BY id DESC
            LIMIT 1
        )
        SELECT
            output.instance_name,
            output.phase1_action,
            output.action,
            output.recommended_type,
            output.phase2_action_changed,
            output.phase2_action_reason,
            output.phase2_decision_details,
            output.blast_radius,
            output.blast_radius_explanation,
            output.relationship_count,
            output.block_reason
        FROM phase2_ec2_outputs output
        JOIN latest_run run ON run.id = output.run_id
        ORDER BY output.blast_radius DESC, output.id
    """
    async with read_connection() as conn:
        records = await conn.fetch(query)

    results: list[GuardrailDecisionResponse] = []
    for record in records:
        row = dict(record)
        blocked = bool(row.get("block_reason")) or _text(row.get("action"), "").upper() in {
            "SKIP",
            "REVIEW",
        }
        outcome = (
            "Blocked"
            if blocked
            else "Changed"
            if row.get("phase2_action_changed")
            else "Kept"
        )
        blast_radius = row.get("blast_radius")
        relationship_count = row.get("relationship_count")
        blast_text = _text(
            row.get("blast_radius_explanation"),
            f"Score {blast_radius or 0}; {relationship_count or 0} relationships",
        )
        results.append(
            GuardrailDecisionResponse(
                resource=_text(row.get("instance_name")),
                originalRecommendation=_action_label(
                    row.get("phase1_action"), row.get("recommended_type")
                ),
                finalDecision=_action_label(
                    row.get("action"), row.get("recommended_type")
                ),
                outcome=outcome,
                risk=_risk(
                    row.get("action"),
                    blast_radius,
                    row.get("block_reason"),
                ),
                blastRadius=blast_text,
                reason=_text(
                    row.get("block_reason")
                    or row.get("phase2_action_reason")
                    or row.get("phase2_decision_details")
                ),
            )
        )
    return results


async def get_phase3_reviews() -> list[Phase3ReviewResponse]:
    ec2_query = """
        WITH latest_run AS (
            SELECT id
            FROM optimization_runs
            ORDER BY id DESC
            LIMIT 1
        )
        SELECT
            COALESCE(resources.name, 'resource-' || output.resource_id::text) AS resource,
            output.verdict,
            output.decision_action,
            output.action,
            output.terraform_action,
            output.terraform_block,
            output.parse_error,
            output.technical_explanation,
            output.decision_rationale,
            output.phase3_created_at
        FROM waste output
        JOIN latest_run run ON run.id = output.run_id
        LEFT JOIN resources ON resources.id = output.resource_id
    """
    s3_query = """
        WITH latest_run AS (
            SELECT id
            FROM optimization_runs
            ORDER BY id DESC
            LIMIT 1
        )
        SELECT
            output.bucket_name AS resource,
            output.verdict,
            output.decision_action,
            output.action,
            output.terraform_action,
            output.terraform_block,
            output.parse_error,
            output.technical_explanation,
            output.decision_rationale,
            output.phase3_created_at
        FROM s3_waste output
        JOIN latest_run run ON run.id = output.run_id
    """
    async with read_connection() as conn:
        ec2_records = await conn.fetch(ec2_query)
        s3_records = await conn.fetch(s3_query)

    rows = [dict(record) for record in (*ec2_records, *s3_records)]
    rows.sort(
        key=lambda row: _sort_timestamp(row.get("phase3_created_at")),
        reverse=True,
    )
    return [
        Phase3ReviewResponse(
            resource=_text(row.get("resource")),
            verdict=_text(row.get("verdict")),
            finalAction=_text(row.get("decision_action") or row.get("action")),
            terraformAction=_text(row.get("terraform_action")),
            terraformBlock=bool(_text(row.get("terraform_block"), "")),
            parseStatus="Parse error"
            if row.get("parse_error")
            else "Parsed"
            if row.get("verdict")
            else UNAVAILABLE,
            explanation=_text(
                row.get("technical_explanation") or row.get("decision_rationale")
            ),
        )
        for row in rows
    ]


async def get_alerts(limit: int = 20) -> list[AlertResponse]:
    failed_runs_query = """
        SELECT id, status, error_message, started_at
        FROM optimization_runs
        WHERE status IN ('failed', 'phase3_failed')
        ORDER BY started_at DESC
        LIMIT $1
    """
    guardrails_query = """
        WITH latest_run AS (
            SELECT id
            FROM optimization_runs
            ORDER BY id DESC
            LIMIT 1
        )
        SELECT instance_name, block_reason, phase2_action_reason, created_at
        FROM phase2_ec2_outputs output
        JOIN latest_run run ON run.id = output.run_id
        WHERE output.block_reason IS NOT NULL OR output.action IN ('SKIP', 'REVIEW')
        ORDER BY output.created_at DESC
        LIMIT $1
    """
    ec2_parse_query = """
        WITH latest_run AS (
            SELECT id
            FROM optimization_runs
            ORDER BY id DESC
            LIMIT 1
        )
        SELECT COALESCE(resources.name, 'resource-' || output.resource_id::text) AS resource,
               output.phase3_created_at AS created_at
        FROM waste output
        JOIN latest_run run ON run.id = output.run_id
        LEFT JOIN resources ON resources.id = output.resource_id
        WHERE output.parse_error IS NOT NULL
        LIMIT $1
    """
    s3_parse_query = """
        WITH latest_run AS (
            SELECT id
            FROM optimization_runs
            ORDER BY id DESC
            LIMIT 1
        )
        SELECT output.bucket_name AS resource, output.phase3_created_at AS created_at
        FROM s3_waste output
        JOIN latest_run run ON run.id = output.run_id
        WHERE output.parse_error IS NOT NULL
        LIMIT $1
    """
    async with read_connection() as conn:
        failed_runs = await conn.fetch(failed_runs_query, limit)
        blocked = await conn.fetch(guardrails_query, limit)
        ec2_parse = await conn.fetch(ec2_parse_query, limit)
        s3_parse = await conn.fetch(s3_parse_query, limit)

    alerts: list[tuple[datetime | None, AlertResponse]] = []
    for record in failed_runs:
        row = dict(record)
        status = _text(row.get("status"))
        alerts.append(
            (
                row.get("started_at"),
                AlertResponse(
                    severity="Critical",
                    type="Pipeline failure",
                    message=_text(
                        row.get("error_message"),
                        f"Optimization run {row['id']} ended with status {status}.",
                    ),
                    resource=f"Run {row['id']}",
                    status="Open",
                    createdAt=_timestamp(row.get("started_at")),
                ),
            )
        )
    for record in blocked:
        row = dict(record)
        alerts.append(
            (
                row.get("created_at"),
                AlertResponse(
                    severity="High",
                    type="Guardrail block",
                    message=_text(
                        row.get("block_reason") or row.get("phase2_action_reason"),
                        "A recommendation requires manual review.",
                    ),
                    resource=_text(row.get("instance_name")),
                    status="Open",
                    createdAt=_timestamp(row.get("created_at")),
                ),
            )
        )
    for record in (*ec2_parse, *s3_parse):
        row = dict(record)
        alerts.append(
            (
                row.get("created_at"),
                AlertResponse(
                    severity="Warning",
                    type="Phase 3 parse",
                    message="Phase 3 output could not be parsed.",
                    resource=_text(row.get("resource")),
                    status="Open",
                    createdAt=_timestamp(row.get("created_at")),
                ),
            )
        )

    alerts.sort(key=lambda alert: _sort_timestamp(alert[0]), reverse=True)
    return [alert for _, alert in alerts[:limit]]


async def get_runs() -> list[RunResponse]:
    query = """
        SELECT
            run.id,
            run.status,
            run.started_at,
            run.completed_at,
            (SELECT COUNT(*) FROM phase1_ec2_outputs ec2 WHERE ec2.run_id = run.id)
                AS ec2_findings,
            (SELECT COUNT(*) FROM phase1_s3_outputs s3 WHERE s3.run_id = run.id)
                AS s3_findings,
            (
                SELECT COUNT(*)
                FROM phase2_ec2_outputs phase2
                WHERE phase2.run_id = run.id
                  AND (phase2.block_reason IS NOT NULL OR phase2.action IN ('SKIP', 'REVIEW'))
            ) AS blocked,
            (
                (SELECT COUNT(*) FROM waste ec2_waste
                 WHERE ec2_waste.run_id = run.id AND ec2_waste.parse_error IS NOT NULL)
                +
                (SELECT COUNT(*) FROM s3_waste s3_waste_output
                 WHERE s3_waste_output.run_id = run.id
                   AND s3_waste_output.parse_error IS NOT NULL)
            ) AS phase3_parse_errors,
            (
                COALESCE(
                    (SELECT SUM(phase2.waste_per_month)
                     FROM phase2_ec2_outputs phase2 WHERE phase2.run_id = run.id),
                    (SELECT SUM(phase1.waste_per_month)
                     FROM phase1_ec2_outputs phase1 WHERE phase1.run_id = run.id),
                    0
                )
                +
                COALESCE(
                    (SELECT SUM(NULLIF(s3.metrics ->> 'estimated_monthly_savings', '')::numeric)
                     FROM phase1_s3_outputs s3 WHERE s3.run_id = run.id),
                    0
                )
            ) AS total_savings
        FROM optimization_runs run
        ORDER BY run.id DESC
        LIMIT 100
    """
    async with read_connection() as conn:
        records = await conn.fetch(query)

    return [
        RunResponse(
            runId=str(row["id"]),
            status=_text(row["status"]),
            startedAt=_timestamp(row["started_at"]),
            completedAt=_timestamp(row["completed_at"]),
            duration=_duration(row["started_at"], row["completed_at"]),
            ec2Findings=int(row["ec2_findings"]),
            s3Findings=int(row["s3_findings"]),
            blocked=int(row["blocked"]),
            phase3ParseErrors=int(row["phase3_parse_errors"]),
            totalSavings=_float(row["total_savings"]),
        )
        for row in (dict(record) for record in records)
    ]


async def get_overview() -> OverviewResponse:
    summary_query = """
        WITH latest_run AS (
            SELECT id, status, started_at, completed_at
            FROM optimization_runs
            ORDER BY id DESC
            LIMIT 1
        )
        SELECT
            run.id,
            run.status,
            run.started_at,
            run.completed_at,
            (SELECT COUNT(*) FROM phase1_ec2_outputs ec2 WHERE ec2.run_id = run.id)
                AS ec2_findings,
            (SELECT COUNT(*) FROM phase1_s3_outputs s3 WHERE s3.run_id = run.id)
                AS s3_findings,
            (
                SELECT COUNT(*) FROM phase2_ec2_outputs phase2
                WHERE phase2.run_id = run.id
                  AND (phase2.block_reason IS NOT NULL OR phase2.action IN ('SKIP', 'REVIEW'))
            ) AS blocked,
            (
                COALESCE(
                    (SELECT SUM(phase2.waste_per_month)
                     FROM phase2_ec2_outputs phase2 WHERE phase2.run_id = run.id),
                    (SELECT SUM(phase1.waste_per_month)
                     FROM phase1_ec2_outputs phase1 WHERE phase1.run_id = run.id),
                    0
                )
                +
                COALESCE(
                    (SELECT SUM(NULLIF(s3.metrics ->> 'estimated_monthly_savings', '')::numeric)
                     FROM phase1_s3_outputs s3 WHERE s3.run_id = run.id),
                    0
                )
            ) AS savings
        FROM latest_run run
    """
    trend_query = """
        SELECT
            run.id,
            run.started_at,
            (
                COALESCE(
                    (SELECT SUM(phase2.waste_per_month)
                     FROM phase2_ec2_outputs phase2 WHERE phase2.run_id = run.id),
                    (SELECT SUM(phase1.waste_per_month)
                     FROM phase1_ec2_outputs phase1 WHERE phase1.run_id = run.id),
                    0
                )
                +
                COALESCE(
                    (SELECT SUM(NULLIF(s3.metrics ->> 'estimated_monthly_savings', '')::numeric)
                     FROM phase1_s3_outputs s3 WHERE s3.run_id = run.id),
                    0
                )
            ) AS savings
        FROM optimization_runs run
        ORDER BY run.id DESC
        LIMIT 6
    """
    types_query = """
        WITH latest_run AS (
            SELECT id FROM optimization_runs ORDER BY id DESC LIMIT 1
        ),
        findings AS (
            SELECT ec2.waste_type AS type
            FROM phase1_ec2_outputs ec2 JOIN latest_run run ON run.id = ec2.run_id
            UNION ALL
            SELECT s3.waste_type AS type
            FROM phase1_s3_outputs s3 JOIN latest_run run ON run.id = s3.run_id
        )
        SELECT type, COUNT(*) AS count
        FROM findings
        GROUP BY type
        ORDER BY count DESC, type
    """
    async with read_connection() as conn:
        summary_record = await conn.fetchrow(summary_query)
        trend_records = await conn.fetch(trend_query)
        type_records = await conn.fetch(types_query)
    alerts = await get_alerts(limit=5)

    if summary_record is None:
        latest = LatestRunSummaryResponse(
            runId=UNAVAILABLE,
            status=UNAVAILABLE,
            duration=UNAVAILABLE,
        )
        total_savings = 0.0
        ec2_count = 0
        s3_count = 0
        blocked_count = 0
    else:
        summary = dict(summary_record)
        latest = LatestRunSummaryResponse(
            runId=str(summary["id"]),
            status=_text(summary["status"]),
            duration=_duration(summary["started_at"], summary["completed_at"]),
        )
        total_savings = _float(summary["savings"])
        ec2_count = int(summary["ec2_findings"])
        s3_count = int(summary["s3_findings"])
        blocked_count = int(summary["blocked"])

    trend = [
        SavingsTrendPointResponse(
            month=row["started_at"].strftime("%b %d"),
            savings=_float(row["savings"]),
        )
        for row in reversed([dict(record) for record in trend_records])
        if row["started_at"] is not None
    ]
    by_type = [
        FindingTypeCountResponse(type=_text(row["type"]), count=int(row["count"]))
        for row in (dict(record) for record in type_records)
    ]
    return OverviewResponse(
        totalEstimatedMonthlySavings=total_savings,
        ec2FindingsCount=ec2_count,
        s3FindingsCount=s3_count,
        blockedRiskyRecommendationsCount=blocked_count,
        latestRun=latest,
        savingsTrend=trend,
        findingsByType=by_type,
        recentAlerts=alerts,
    )
