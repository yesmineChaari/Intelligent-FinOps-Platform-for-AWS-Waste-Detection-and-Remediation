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


def _get_metric(table_name, metric_name, stat, operation=None):
    end   = datetime.now(timezone.utc)
    start = end - timedelta(minutes=LOOKBACK_MINUTES)
    dims  = [{"Name": "TableName", "Value": table_name}]
    if operation:
        dims.append({"Name": "Operation", "Value": operation})
    try:
        resp = cloudwatch.get_metric_statistics(
            Namespace="AWS/DynamoDB", MetricName=metric_name,
            Dimensions=dims, StartTime=start, EndTime=end,
            Period=PERIOD, Statistics=[stat],
        )
        pts = resp.get("Datapoints", [])
        if not pts:
            return None
        return sorted(pts, key=lambda d: d["Timestamp"])[-1].get(stat)
    except Exception as e:
        logger.warning(f"[dynamodb_metrics] CW error {table_name}/{metric_name}: {e}")
        return None


def _collect(cur, resource_id, table_name):
    now = datetime.now(timezone.utc)

    cur.execute("SELECT read_capacity, write_capacity FROM dynamodb_instances WHERE resource_id=%s", (resource_id,))
    prov      = cur.fetchone()
    read_cap  = float(prov[0]) if prov and prov[0] else None
    write_cap = float(prov[1]) if prov and prov[1] else None

    get_lat = _get_metric(table_name, "SuccessfulRequestLatency", "Average", "GetItem")
    put_lat = _get_metric(table_name, "SuccessfulRequestLatency", "Average", "PutItem")
    latency = round((get_lat + put_lat) / 2, 4) if get_lat and put_lat else (get_lat or put_lat)

    cur.execute(
        """
        INSERT INTO dynamodb_metrics (timestamp, resource_id, read_capacity_units, write_capacity_units,
                                      consumed_read_cu, consumed_write_cu, throttled_requests, latency_ms)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (timestamp, resource_id) DO NOTHING
        """,
        (now, resource_id, read_cap, write_cap,
         _get_metric(table_name, "ConsumedReadCapacityUnits",  "Sum"),
         _get_metric(table_name, "ConsumedWriteCapacityUnits", "Sum"),
         _get_metric(table_name, "ThrottledRequests",          "Sum"),
         latency)
    )


def run_dynamodb_metrics_collection():
    logger.info("[dynamodb_metrics] Starting...")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.id, d.name FROM resources r
                JOIN dynamodb_instances d ON d.resource_id = r.id
                WHERE r.resource_type = 'dynamodb'
            """)
            rows = cur.fetchall()
            for resource_id, name in rows:
                try:
                    _collect(cur, resource_id, name)
                except Exception as e:
                    logger.error(f"[dynamodb_metrics] Failed {name}: {e}")
    logger.info(f"[dynamodb_metrics] Done — {len(rows)} tables")
