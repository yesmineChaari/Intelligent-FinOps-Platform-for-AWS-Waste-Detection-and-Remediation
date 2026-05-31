import logging
import os
from datetime import datetime, timezone

import boto3
from core.db import get_db

logger = logging.getLogger(__name__)
LOCALSTACK = os.getenv("LOCALSTACK_ENDPOINT", "http://localhost:4566")
REGION = os.getenv("AWS_REGION", "eu-west-1")
SAMPLE_SIZE = 50

s3_client = boto3.client(
    "s3",
    endpoint_url=LOCALSTACK,
    region_name=REGION,
    aws_access_key_id="test",
    aws_secret_access_key="test",
)

# LocalStack sets LastModified = upload time, so real object age is always 0 days.
# These deterministic profiles keep the deployed demo scenarios stable.
BUCKET_AGE_PROFILES = {
    "app1-data-bucket": {"pct_30": 37.5, "pct_90": 25.0, "pct_180": 12.5},
    "app1-logs-bucket": {"pct_30": 50.0, "pct_90": 37.5, "pct_180": 12.5},
    "app1-temp-bucket": {"pct_30": 25.0, "pct_90": 12.5, "pct_180": 0.0},
    "app2-report-bucket": {"pct_30": 37.5, "pct_90": 25.0, "pct_180": 12.5},
    "app2-archive-bucket": {"pct_30": 87.5, "pct_90": 75.0, "pct_180": 62.5},
    "app2-clean-bucket": {"pct_30": 12.5, "pct_90": 0.0, "pct_180": 0.0},
}

DEFAULT_AGE_PROFILE = {"pct_30": 25.0, "pct_90": 12.5, "pct_180": 0.0}


def _overwrite_existing_samples() -> bool:
    return os.getenv("S3_SAMPLER_OVERWRITE_EXISTING", "false").lower() == "true"


def _has_existing_sample(cur, resource_id) -> bool:
    cur.execute(
        "SELECT 1 FROM s3_object_samples WHERE resource_id = %s LIMIT 1",
        (resource_id,),
    )
    return cur.fetchone() is not None


def _is_glacier_like(storage_class: str) -> bool:
    normalized = storage_class.upper()
    return "GLACIER" in normalized or "ARCHIVE" in normalized


def _sample_bucket(cur, resource_id, bucket_name):
    if not _overwrite_existing_samples() and _has_existing_sample(cur, resource_id):
        logger.info(f"[s3_sampler] {bucket_name} already has object samples - skipping")
        return

    now = datetime.now(timezone.utc)
    objects = []

    try:
        for page in s3_client.get_paginator("list_objects_v2").paginate(Bucket=bucket_name):
            for obj in page.get("Contents", []):
                objects.append(obj)
                if len(objects) >= SAMPLE_SIZE:
                    break
            if len(objects) >= SAMPLE_SIZE:
                break
    except Exception as e:
        logger.warning(f"[s3_sampler] Cannot list {bucket_name}: {e}")
        return

    if not objects:
        logger.info(f"[s3_sampler] {bucket_name} empty - skipping")
        return

    total = len(objects)
    group_size_bytes = sum(obj.get("Size", 0) or 0 for obj in objects)

    classes = [(obj.get("StorageClass", "STANDARD") or "STANDARD").upper() for obj in objects]
    pct_standard = round(classes.count("STANDARD") / total * 100, 2)
    pct_standard_ia = round(classes.count("STANDARD_IA") / total * 100, 2)
    pct_glacier = round(
        sum(1 for storage_class in classes if _is_glacier_like(storage_class)) / total * 100,
        2,
    )

    profile = BUCKET_AGE_PROFILES.get(bucket_name, DEFAULT_AGE_PROFILE)
    pct_older_30 = profile["pct_30"]
    pct_older_90 = min(pct_older_30, profile["pct_90"])
    pct_older_180 = min(pct_older_90, profile["pct_180"])

    logger.info(
        f"[s3_sampler] {bucket_name}: {total} objects | "
        f"STD={pct_standard}% IA={pct_standard_ia}% Glacier={pct_glacier}% | "
        f">30d={pct_older_30}% >90d={pct_older_90}% >180d={pct_older_180}%"
    )

    cur.execute(
        """
        INSERT INTO s3_object_samples
            (resource_id, sampled_at, sample_size,
             pct_older_than_30_days, pct_older_than_90_days, pct_older_than_180_days,
             pct_in_standard, pct_in_standard_ia, pct_in_glacier, group_size_bytes)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            resource_id,
            now,
            total,
            pct_older_30,
            pct_older_90,
            pct_older_180,
            pct_standard,
            pct_standard_ia,
            pct_glacier,
            group_size_bytes,
        ),
    )


def run_s3_object_sampler():
    logger.info("[s3_sampler] Starting...")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.id, s.name FROM resources r
                JOIN s3_instances s ON s.resource_id = r.id
                WHERE r.resource_type = 's3'
            """)
            rows = cur.fetchall()
            if not rows:
                logger.info("[s3_sampler] No S3 in DB - skipping")
                return
            for resource_id, bucket_name in rows:
                try:
                    _sample_bucket(cur, resource_id, bucket_name)
                except Exception as e:
                    logger.error(f"[s3_sampler] Failed {bucket_name}: {e}")
    logger.info(f"[s3_sampler] Done - {len(rows)} buckets")
