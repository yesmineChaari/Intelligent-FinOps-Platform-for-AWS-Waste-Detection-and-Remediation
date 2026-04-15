"""
All database queries for Phase 1.
All metric queries use mathematically defensible percentiles and standard deviations.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
import asyncpg

async def get_all_instances(conn: asyncpg.Connection) -> list[dict]:
    rows = await conn.fetch("""
        SELECT
            r.id              AS resource_id,
            r.name            AS resource_name,
            r.resource_type,
            e.instance_type,
            e.region,
            e.status,
            e.launched_at,
            e.role::text      AS role,
            e.environment,
            e.team,
            e.os::text        AS os
        FROM ec2_instances e
        JOIN resources r ON r.id = e.resource_id
    """)
    return [dict(r) for r in rows]


async def get_instance_metrics(
    conn: asyncpg.Connection,
    resource_id: int,
    window_days: int
) -> Optional[dict]:
    """
    Returns advanced statistical metrics over the window: 
    P95 CPU, P99 CPU, Max CPU, P95 RAM, and Coefficient of Variation (CV).
    """
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    row = await conn.fetchrow("""
        SELECT
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY cpu_pct) AS p95_cpu,
            PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY cpu_pct) AS p99_cpu,
            MAX(cpu_pct) AS max_cpu,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY ram_pct) AS p95_ram,
            -- CV = Standard Deviation / Mean. Protect against divide-by-zero.
            CASE 
                WHEN AVG(cpu_pct) > 0 THEN STDDEV(cpu_pct) / AVG(cpu_pct) 
                ELSE 0 
            END AS cv
        FROM ec2_metrics
        WHERE resource_id = $1
          AND timestamp >= $2
    """, resource_id, since)

    if row is None or row["p95_cpu"] is None:
        return None

    return {
        "p95_cpu": float(row["p95_cpu"]),
        "p99_cpu": float(row["p99_cpu"]),
        "max_cpu": float(row["max_cpu"]),
        "p95_ram": float(row["p95_ram"]),
        "cv": float(row["cv"]),
    }


async def is_zombie(
    conn: asyncpg.Connection,
    resource_id: int,
    stopped_days_threshold: int
) -> tuple[bool, int | None]:
    """Return zombie decision plus days since last EC2 metric timestamp."""

    row = await conn.fetchrow("""
        SELECT
            e.status,
            CASE
                WHEN MAX(m.timestamp) IS NULL THEN NULL
                ELSE FLOOR(EXTRACT(EPOCH FROM (NOW() - MAX(m.timestamp))) / 86400)::int
            END AS days_since_last_metric,
            COALESCE(
                MAX(m.timestamp) <= NOW() - ($2 * INTERVAL '1 day'),
                TRUE
            ) AS stale_metrics
        FROM ec2_instances e
        LEFT JOIN ec2_metrics m ON m.resource_id = e.resource_id
        WHERE e.resource_id = $1
        GROUP BY e.status
    """, resource_id, stopped_days_threshold)

    if row is None:
        return False, None

    stopped = row["status"] == "stopped"
    stale_metrics = bool(row["stale_metrics"])
    days_since_last_metric = row["days_since_last_metric"]
    if days_since_last_metric is not None:
        days_since_last_metric = int(days_since_last_metric)

    return stopped and stale_metrics, days_since_last_metric


async def get_sizing_ladder(
    conn: asyncpg.Connection,
    instance_family: str,
    region: str,
    os_type: str
) -> list[dict]:
    """
    Returns all instances in the family for the specific region and OS.
    """
    rows = await conn.fetch("""
        SELECT instance_type, ladder_rank, vcpu, ram_gb, price_per_hour
        FROM pricing
        WHERE instance_family = $1
          AND region = $2
                    AND lower(os) = lower($3)
        ORDER BY ladder_rank ASC
    """, instance_family, region, os_type)

    return [dict(r) for r in rows]


async def get_instance_price(
    conn: asyncpg.Connection,
    instance_type: str,
    region: str,
    os_type: str
) -> Optional[float]:
    """Get precise price for the specific type, region, and OS."""
    row = await conn.fetchrow("""
        SELECT price_per_hour
        FROM pricing
        WHERE instance_type = $1
          AND region = $2
                    AND lower(os) = lower($3)
        LIMIT 1
    """, instance_type, region, os_type)
    return float(row["price_per_hour"]) if row else None