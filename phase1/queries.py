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
            instance_id,
            instance_type,      
            status,
            launched_at,
            role,
            os,
            region,
            environment,
            team
        FROM resources
        WHERE resource_type = 'ec2'
    """)
    return [dict(r) for r in rows]


async def get_instance_metrics(
    conn: asyncpg.Connection,
    instance_id: str,
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
        WHERE instance_id = $1
          AND timestamp >= $2
    """, instance_id, since)

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
    instance_id: str,
    stopped_days_threshold: int
) -> bool:
    """Zombie = stopped for more than N days. No CPU/Network logic needed."""
    since = datetime.now(timezone.utc) - timedelta(days=stopped_days_threshold)

    row = await conn.fetchrow("""
        SELECT status, launched_at
        FROM resources
        WHERE instance_id = $1
    """, instance_id)

    if row is None:
        return False

    stopped = row["status"] == "stopped"
    old_enough = row["launched_at"] is not None and row["launched_at"] <= since

    return stopped and old_enough


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
          AND os = $3
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
          AND os = $3
        LIMIT 1
    """, instance_type, region, os_type)
    return float(row["price_per_hour"]) if row else None