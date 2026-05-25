import logging
import os
from datetime import datetime, timezone, timedelta

import boto3
from core.db import get_db

logger     = logging.getLogger(__name__)
LOCALSTACK = os.getenv("LOCALSTACK_ENDPOINT", "http://localhost:4566")
REGION     = os.getenv("AWS_REGION", "eu-west-1")

cloudwatch = boto3.client("cloudwatch", endpoint_url=LOCALSTACK, region_name=REGION,
                          aws_access_key_id="test", aws_secret_access_key="test")

PERIOD           = 300
LOOKBACK_MINUTES = 10


def _get_metric(bucket_name, metric_name, stat, storage_type=None):
    end   = datetime.now(timezone.utc)
    start = end - timedelta(minutes=LOOKBACK_MINUTES)
    dims  = [{"Name": "BucketName", "Value": bucket_name}]
    if storage_type:
        dims.append({"Name": "StorageType", "Value": storage_type})
    try:
        resp = cloudwatch.get_metric_statistics(
            Namespace="AWS/S3", MetricName=metric_name,
            Dimensions=dims, StartTime=start, EndTime=end,
            Period=PERIOD, Statistics=[stat],
        )
        pts = resp.get("Datapoints", [])
        if not pts:
            return None
        return sorted(pts, key=lambda d: d["Timestamp"])[-1].get(stat)
    except Exception as e:
        logger.warning(f"[s3_metrics] CW error {bucket_name}/{metric_name}: {e}")
        return None


def _collect(cur, resource_id, bucket_name):
    now = datetime.now(timezone.utc)
    cur.execute(
        """
        INSERT INTO s3_metrics (timestamp, resource_id, bucket_size_bytes, num_objects,
                                get_requests, put_requests, bytes_downloaded, bytes_uploaded)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (timestamp, resource_id) DO NOTHING
        """,
        (
            now, resource_id,
            _get_metric(bucket_name, "BucketSizeBytes",  "Average", "StandardStorage"),
            _get_metric(bucket_name, "NumberOfObjects",  "Average", "AllStorageTypes"),
            _get_metric(bucket_name, "GetRequests",      "Sum"),
            _get_metric(bucket_name, "PutRequests",      "Sum"),
            _get_metric(bucket_name, "BytesDownloaded",  "Sum"),
            _get_metric(bucket_name, "BytesUploaded",    "Sum"),
        )
    )


def run_s3_metrics_collection():
    logger.info("[s3_metrics] Starting...")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.id, s.name FROM resources r
                JOIN s3_instances s ON s.resource_id = r.id
                WHERE r.resource_type = 's3'
            """)
            rows = cur.fetchall()
            for resource_id, name in rows:
                try:
                    _collect(cur, resource_id, name)
                except Exception as e:
                    logger.error(f"[s3_metrics] Failed {name}: {e}")
    logger.info(f"[s3_metrics] Done — {len(rows)} buckets")
