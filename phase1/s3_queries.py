"""
S3 database queries for Phase 1.
Mirrors the exact same pattern as queries.py for EC2.

Agent 1 never calls LocalStack. It only reads what Agent 0 already stored:
    - s3_instances       → bucket metadata + has_lifecycle flag
  - s3_metrics         → CloudWatch GetRequests + PutRequests per day
  - s3_object_samples  → pre-aggregated pct fields written by Agent 0

No AWS API calls here. Pure DB reads.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
import asyncpg


# Returns all buckets from s3_instances
async def get_all_buckets(conn: asyncpg.Connection) -> list[dict]:
    """
    Fetch every S3 bucket Agent 0 discovered.
    Equivalent of get_all_instances() for EC2.
    Returns a bucket_name key for compatibility with detection logic.
    """
    rows = await conn.fetch("""
        SELECT
            s.name AS bucket_name,
            s.resource_id,
            s.region,
            s.creation_date,
            s.object_count,
            s.size_bytes,
            s.has_lifecycle,
            s.environment,
            s.team
        FROM s3_instances s
        ORDER BY s.name
    """)
    return [dict(r) for r in rows]


# Returns total requests by bucket_name over time window
async def get_bucket_request_total(
    conn: asyncpg.Connection,
    bucket_name: str,
    window_days: int
) -> Optional[float]:
    """
    Returns total GET + PUT requests over the window.
    Agent 0 stored these from CloudWatch put_metric_data / get_metric_statistics.
    Returns None if no metric rows exist for this bucket in the window.
    Used by Rule 2 : abandoned bucket detection.
    """
    since = datetime.now(timezone.utc) - timedelta(days=window_days)

    row = await conn.fetchrow("""
        SELECT
            COUNT(*) AS metric_points,
            COALESCE(SUM(m.get_requests + m.put_requests), 0) AS total_requests
        FROM s3_metrics m
        JOIN s3_instances s ON s.resource_id = m.resource_id
        WHERE s.name = $1
          AND m.timestamp >= $2
    """, bucket_name, since)

    if row is None or int(row["metric_points"]) == 0:
        return None

    return float(row["total_requests"])


# Returns object samples results for specific bucket_name
async def get_latest_object_sample(
    conn: asyncpg.Connection,
    bucket_name: str
) -> Optional[dict]:
    """
    Returns the most recent sampling run summary for this bucket.
    Agent 0 calculated these percentages from list_objects_v2 and stored them.
    Agent 1 reads them directly : no recalculation needed.
    Used by Rule 3 : storage class mismatch detection.

    We take only the most recent sampled_at to avoid mixing historical samples.
    """
    row = await conn.fetchrow("""
        SELECT
            os.sample_size,
            os.pct_older_than_30_days,
            os.pct_older_than_90_days,
            os.pct_older_than_180_days,
            os.pct_in_standard,
            os.pct_in_standard_ia,
            os.pct_in_glacier,
            os.sampled_at
        FROM s3_object_samples os
        JOIN s3_instances s ON s.resource_id = os.resource_id
        WHERE s.name = $1
        ORDER BY os.sampled_at DESC
        LIMIT 1
    """, bucket_name)

    if row is None:
        return None

    return {
        "sample_size":              int(row["sample_size"]),
        "pct_older_than_30_days":   float(row["pct_older_than_30_days"]),
        "pct_older_than_90_days":   float(row["pct_older_than_90_days"]),
        "pct_older_than_180_days":  float(row["pct_older_than_180_days"]),
        "pct_in_standard":          float(row["pct_in_standard"]),
        "pct_in_standard_ia":       float(row["pct_in_standard_ia"]),
        "pct_in_glacier":           float(row["pct_in_glacier"]),
        "sampled_at":               row["sampled_at"],
    }
