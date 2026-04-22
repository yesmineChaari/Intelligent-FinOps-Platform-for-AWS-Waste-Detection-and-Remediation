"""
S3 database reads for Phase 1 detection.
Reads only pre-collected data written by upstream ingestion.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg


async def get_all_buckets(conn: asyncpg.Connection) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT
            s.resource_id,
            s.name AS bucket_name,
            s.region,
            s.creation_date,
            s.object_count,
            s.size_bytes,
            s.has_lifecycle,
            s.environment,
            s.team
        FROM s3_instances s
        ORDER BY s.name
        """
    )
    return [dict(r) for r in rows]


async def get_bucket_request_total(
    conn: asyncpg.Connection,
    resource_id: int,
    window_days: int,
) -> Optional[float]:
    since = datetime.now(timezone.utc) - timedelta(days=window_days)

    row = await conn.fetchrow(
        """
        SELECT
            COUNT(*) AS sample_count,
            COALESCE(SUM(get_requests + put_requests), 0) AS total_requests
        FROM s3_metrics
        WHERE resource_id = $1
          AND timestamp >= $2
        """,
        resource_id,
        since,
    )

    if row is None or int(row["sample_count"]) == 0:
        return None

    return float(row["total_requests"])


async def get_latest_object_samples(
    conn: asyncpg.Connection,
    resource_id: int,
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT DISTINCT ON (grouping_key)
            grouping_key,
            sample_size,
            pct_older_than_30_days,
            pct_older_than_90_days,
            pct_older_than_180_days,
            pct_in_standard,
            pct_in_standard_ia,
            pct_in_glacier,
            sampled_at
        FROM s3_object_samples
        WHERE resource_id = $1
        ORDER BY grouping_key, sampled_at DESC
        """,
        resource_id,
    )

    return [
        {
            "grouping_key": row["grouping_key"],
            "sample_size": int(row["sample_size"]),
            "pct_older_than_30_days": float(row["pct_older_than_30_days"]),
            "pct_older_than_90_days": float(row["pct_older_than_90_days"]),
            "pct_older_than_180_days": float(row["pct_older_than_180_days"]),
            "pct_in_standard": float(row["pct_in_standard"]),
            "pct_in_standard_ia": float(row["pct_in_standard_ia"]),
            "pct_in_glacier": float(row["pct_in_glacier"]),
        }
        for row in rows
    ]
