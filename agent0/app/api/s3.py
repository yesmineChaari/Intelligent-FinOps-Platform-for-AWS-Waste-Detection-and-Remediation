from fastapi import APIRouter, HTTPException
from core.db import get_connection

router = APIRouter()


@router.get("/")
def list_s3_buckets():
    """List all S3 buckets with metadata."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.id, r.name, s.region, s.status, s.role,
                       s.environment, s.team, s.object_count, s.size_bytes,
                       s.has_lifecycle, s.creation_date
                FROM resources r
                JOIN s3_instances s ON s.resource_id = r.id
                WHERE r.resource_type = 's3'
                ORDER BY r.name
            """)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


@router.get("/{name}")
def get_s3_bucket(name: str):
    """Get a single S3 bucket by name."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.id, r.name, s.region, s.status, s.role,
                       s.environment, s.team, s.object_count, s.size_bytes,
                       s.has_lifecycle, s.creation_date
                FROM resources r
                JOIN s3_instances s ON s.resource_id = r.id
                WHERE r.resource_type = 's3' AND r.name = %s
            """, (name,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"S3 bucket '{name}' not found")
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))


@router.get("/{name}/metrics")
def get_s3_metrics(name: str, limit: int = 30):
    """Get recent S3 bucket-level metrics."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM resources WHERE name = %s AND resource_type = 's3'", (name,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"S3 bucket '{name}' not found")

            cur.execute("""
                SELECT timestamp, bucket_size_bytes, num_objects,
                       get_requests, put_requests, bytes_downloaded, bytes_uploaded
                FROM s3_metrics
                WHERE resource_id = %s
                ORDER BY timestamp DESC
                LIMIT %s
            """, (row[0], limit))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/{name}/samples")
def get_s3_object_samples(name: str, limit: int = 10):
    """
    Get object-level storage class and age distribution samples.
    Each row = one sampler run. Most recent first.
    Populated by the s3_sampler service via list_objects_v2.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM resources WHERE name = %s AND resource_type = 's3'", (name,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"S3 bucket '{name}' not found")

            cur.execute("""
                SELECT id, sampled_at, sample_size,
                       pct_older_than_30_days, pct_older_than_90_days, pct_older_than_180_days,
                       pct_in_standard, pct_in_standard_ia, pct_in_glacier
                FROM s3_object_samples
                WHERE resource_id = %s
                ORDER BY sampled_at DESC
                LIMIT %s
            """, (row[0], limit))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/{name}/samples/latest")
def get_s3_latest_sample(name: str):
    """
    Most recent object sample for a bucket.
    This is what the waste engine reads to decide lifecycle recommendations.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM resources WHERE name = %s AND resource_type = 's3'", (name,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"S3 bucket '{name}' not found")

            cur.execute("""
                SELECT id, sampled_at, sample_size,
                       pct_older_than_30_days, pct_older_than_90_days, pct_older_than_180_days,
                       pct_in_standard, pct_in_standard_ia, pct_in_glacier
                FROM s3_object_samples
                WHERE resource_id = %s
                ORDER BY sampled_at DESC
                LIMIT 1
            """, (row[0],))
            r = cur.fetchone()
            if not r:
                raise HTTPException(status_code=404, detail=f"No samples yet for bucket '{name}'")
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, r))
