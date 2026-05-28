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


def _get_metric(instance_id, metric_name, namespace, stat):
    end   = datetime.now(timezone.utc)
    start = end - timedelta(minutes=LOOKBACK_MINUTES)
    try:
        resp = cloudwatch.get_metric_statistics(
            Namespace=namespace, MetricName=metric_name,
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            StartTime=start, EndTime=end, Period=PERIOD, Statistics=[stat],
        )
        pts = resp.get("Datapoints", [])
        if not pts:
            return None
        return sorted(pts, key=lambda d: d["Timestamp"])[-1].get(stat)
    except Exception as e:
        logger.warning(f"[ec2_metrics] CW error {instance_id}/{metric_name}: {e}")
        return None


def _bytes_to_mbps(value):
    if value is None:
        return None
    return round((float(value) * 8) / 1_000_000, 4)


def _bytes_to_mb(value):
    if value is None:
        return None
    return round(float(value) / 1_000_000, 4)


def _collect(cur, resource_id, instance_name):
    now             = datetime.now(timezone.utc)
    cpu             = _get_metric(instance_name, "CPUUtilization",   "AWS/EC2", "Average")
    ram             = _get_metric(instance_name, "mem_used_percent", "CWAgent", "Average")
    raw_network_in  = _get_metric(instance_name, "NetworkIn",        "AWS/EC2", "Sum")
    raw_network_out = _get_metric(instance_name, "NetworkOut",       "AWS/EC2", "Sum")
    raw_disk_read   = _get_metric(instance_name, "DiskReadBytes",    "AWS/EC2", "Sum")
    raw_disk_write  = _get_metric(instance_name, "DiskWriteBytes",   "AWS/EC2", "Sum")

    if all(v is None for v in [cpu, ram, raw_network_in, raw_network_out, raw_disk_read, raw_disk_write]):
        logger.debug(f"[ec2_metrics] No metrics for {instance_name} — zombie/stopped")
        return

    network_in = _bytes_to_mbps(raw_network_in)
    network_out = _bytes_to_mbps(raw_network_out)
    disk_read = _bytes_to_mb(raw_disk_read)
    disk_write = _bytes_to_mb(raw_disk_write)

    logger.debug(
        "[ec2_metrics] %s raw_io=(network_in=%s, network_out=%s, disk_read=%s, disk_write=%s) normalized_io=(network_in=%s, network_out=%s, disk_read=%s, disk_write=%s)",
        instance_name,
        raw_network_in,
        raw_network_out,
        raw_disk_read,
        raw_disk_write,
        network_in,
        network_out,
        disk_read,
        disk_write,
    )

    cur.execute(
        """
        INSERT INTO ec2_metrics (timestamp, resource_id, cpu_pct, ram_pct, network_in, network_out, disk_read, disk_write)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (timestamp, resource_id) DO NOTHING
        """,
        (now, resource_id, cpu, ram, network_in, network_out, disk_read, disk_write)
    )


def run_ec2_metrics_collection():
    logger.info("[ec2_metrics] Starting...")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.id, e.name FROM resources r
                JOIN ec2_instances e ON e.resource_id = r.id
                WHERE r.resource_type = 'ec2'
            """)
            rows = cur.fetchall()
            for resource_id, name in rows:
                try:
                    _collect(cur, resource_id, name)
                except Exception as e:
                    logger.error(f"[ec2_metrics] Failed {name}: {e}")
    logger.info(f"[ec2_metrics] Done — {len(rows)} instances")
