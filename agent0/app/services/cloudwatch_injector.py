import logging
import os
import random
from datetime import datetime, timezone

import boto3

logger     = logging.getLogger(__name__)
LOCALSTACK = os.getenv("LOCALSTACK_ENDPOINT", "http://localhost:4566")
REGION     = os.getenv("AWS_REGION", "eu-west-1")

cloudwatch = boto3.client(
    "cloudwatch",
    endpoint_url=LOCALSTACK,
    region_name=REGION,
    aws_access_key_id="test",
    aws_secret_access_key="test",
)

# ── EC2 profiles ──────────────────────────────────────────────────────────────
#
# i-001  dependant_primary    → DOWNSIZE (p95_cpu ~62, p95_ram ~68 — above idle
#                               thresholds of 10/20, but instance is oversized
#                               at current size; stays CLEAN or DOWNSIZE depending
#                               on pricing ladder)
#                               Realistically: high-utilisation primary, CLEAN.
#
# i-002  dependant_secondary  → SKIP (skipped role; metrics emitted so zombie
#                               check passes first)
#
# i-003  steady               → STOP (idle: p95_cpu < 5, p95_ram < 10,
#                               max_cpu < 20 over 7-day window)
#
# i-004  bursty               → DOWNSIZE (cv ≥ 0.5 passes tag-error check;
#                               p99_cpu < 30 triggers oversized)
#                               Profile: mostly idle with sharp spikes → high CV,
#                               low p99 overall because spikes are rare.
#
# i-005  backup               → SKIP (skipped role)
#
# i-006  zombie/stopped       → no metrics emitted; DB status=stopped + stale
#                               timestamp triggers TERMINATE in detection.
#
# Network/disk units: Bytes/s emitted as a single-datapoint proxy.
# The collector aggregates over the window; these values feed p95/p99/max
# calculations in ec2_metrics after collection.

EC2_PROFILES = {
    # dependant_primary — genuinely busy: high CPU, active IO
    # Detection: p95_cpu ~60 ≥ 10, p95_ram ~65 ≥ 20 → CLEAN (not idle, not oversized)
    "i-001": {
        "cpu_base": 58.0, "cpu_var": 10.0,
        "ram_base": 65.0, "ram_var":  7.0,
        "net":   6_000_000,
        "disk_r": 1_500_000, "disk_w": 3_000_000,
    },

    # dependant_secondary — moderate load, skipped role anyway
    # Metrics emitted so it doesn't trip the running-zombie check
    # (max_cpu well above 1.5 threshold)
    "i-002": {
        "cpu_base": 22.0, "cpu_var": 6.0,
        "ram_base": 38.0, "ram_var": 5.0,
        "net":   1_800_000,
        "disk_r":   400_000, "disk_w":   600_000,
    },

    # steady — genuinely idle
    # Targets: p95_cpu < 5, p95_ram < 10, max_cpu < 20  → STOP
    # cpu_base=3 with var=1.5 keeps p95 well under 5; max stays under 7
    # ram_base=7 with var=2   keeps p95 under 10
    "i-003": {
        "cpu_base":  3.0, "cpu_var": 1.5,
        "ram_base":  7.0, "ram_var": 2.0,
        "net":     900_000,
        "disk_r":  200_000, "disk_w":  800_000,
    },

    # bursty — bimodal: mostly quiet with occasional CPU spikes
    # CV = std/mean.  idle_weight=0.85 → mean stays low (~8),
    # but spike values (~65) push std high → cv well above 0.5 ✓
    # p99_cpu: with 85% datapoints near 5 and 15% near 65,
    # p99 lands around 20-25 < 30 → DOWNSIZE ✓
    # Emitted as two alternating bands; the scheduler calls inject
    # every tick so over many ticks the distribution builds correctly.
    "i-004": {
        # idle band
        "cpu_idle_base":  5.0, "cpu_idle_var":  2.0,
        "ram_idle_base": 20.0, "ram_idle_var":  4.0,
        # spike band (fires ~15 % of ticks)
        "cpu_spike_base": 65.0, "cpu_spike_var": 10.0,
        "ram_spike_base": 55.0, "ram_spike_var":  8.0,
        "spike_prob": 0.15,
        "net":    3_500_000,
        "disk_r":   800_000, "disk_w": 1_200_000,
    },

    # backup — skipped role; low CPU so it would be idle if not skipped
    "i-005": {
        "cpu_base":  5.0, "cpu_var": 1.5,
        "ram_base": 18.0, "ram_var": 3.0,
        "net":     300_000,
        "disk_r":  100_000, "disk_w": 8_000_000,
    },

    # i-006 intentionally omitted — no metrics → zombie detection fires
}

# ── DynamoDB profiles ─────────────────────────────────────────────────────────
# r-001: PROVISIONED 100/100 RCU/WCU, consumed ~8/~5 → over-provisioned

DYNAMODB_TABLES = {
    "r-001": {
        "rcu_base": 8.0,  "rcu_var": 3.0,
        "wcu_base": 5.0,  "wcu_var": 2.0,
    },
}

# ── S3 profiles ───────────────────────────────────────────────────────────────
#
# r-002  primary active bucket
#        → Missing lifecycle (has_lifecycle=False in DB) + high GET traffic
#        → RECOMMEND_LIFECYCLE (missing_lifecycle rule)
#        object_count: 1 200   gets: ~85/tick   puts: ~8/tick
#        Total requests over 30 days >> 10 → NOT abandoned
#
# r-003  log-write bucket
#        → High PUT, low GET; no lifecycle
#        → RECOMMEND_LIFECYCLE; not abandoned (puts >> 10/month)
#        object_count: 4 500   gets: ~3/tick    puts: ~36/tick
#
# r-004  cold archive bucket
#        → Near-zero requests → abandoned (SUM get+put ≤ 10 over 30 days)
#        → REVIEW (abandoned rule)
#        object_count: 12 000  gets: ~0/tick    puts: ~0/tick
#        gets_base/puts_base kept fractional so most ticks emit 0,
#        keeping the 30-day sum safely under 10.
#
# NumberOfObjects is now per-bucket (was hardcoded to 8 — broken).
# BucketSizeBytes uses StandardStorage dimension as required by AWS/S3 schema.

S3_PROFILES = {
    "r-002": {
        "object_count":    1_200,
        "size":          850_000_000,
        "gets_base":  85,   "gets_var":  20,
        "puts_base":   8,   "puts_var":   3,
        "dl_base":   2_500_000, "dl_var":   500_000,
        "ul_base":     900_000, "ul_var":   200_000,
    },
    "r-003": {
        "object_count":    4_500,
        "size":          620_000_000,
        "gets_base":   3,   "gets_var":   2,
        "puts_base":  36,   "puts_var":  10,
        "dl_base":     160_000, "dl_var":    50_000,
        "ul_base":   1_900_000, "ul_var":   400_000,
    },
    "r-004": {
        "object_count":   12_000,
        "size":        3_200_000_000,
        # fractional base → most ticks round to 0; over 30 days total ≤ 10
        "gets_base":  0.15,  "gets_var": 0.15,
        "puts_base":  0.10,  "puts_var": 0.10,
        "dl_base":      10_000, "dl_var":     5_000,
        "ul_base":      25_000, "ul_var":    10_000,
    },
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _put(namespace: str, metric_name: str, dims: list, value: float, unit: str) -> None:
    cloudwatch.put_metric_data(
        Namespace=namespace,
        MetricData=[{
            "MetricName": metric_name,
            "Dimensions": dims,
            "Timestamp":  datetime.now(timezone.utc),
            "Value":      max(0.0, value),
            "Unit":       unit,
        }],
    )


def _uniform(base: float, var: float) -> float:
    return base + random.uniform(-var, var)


# ── per-service injectors ─────────────────────────────────────────────────────

def inject_ec2_metrics() -> None:
    for iid, p in EC2_PROFILES.items():
        dims = [{"Name": "InstanceId", "Value": iid}]

        # Bursty instance uses a bimodal distribution
        if "spike_prob" in p:
            if random.random() < p["spike_prob"]:
                cpu = round(min(99.9, max(0.1, _uniform(p["cpu_spike_base"], p["cpu_spike_var"]))), 2)
                ram = round(min(99.9, max(1.0,  _uniform(p["ram_spike_base"], p["ram_spike_var"]))), 2)
            else:
                cpu = round(min(99.9, max(0.1, _uniform(p["cpu_idle_base"], p["cpu_idle_var"]))), 2)
                ram = round(min(99.9, max(1.0,  _uniform(p["ram_idle_base"], p["ram_idle_var"]))), 2)
        else:
            cpu = round(min(99.9, max(0.1, _uniform(p["cpu_base"], p["cpu_var"]))), 2)
            ram = round(min(99.9, max(1.0,  _uniform(p["ram_base"], p["ram_var"]))), 2)

        net_in  = p["net"] * random.uniform(0.7, 1.3)
        net_out = p["net"] * random.uniform(0.3, 0.8)

        _put("AWS/EC2",  "CPUUtilization",   dims, cpu,                                    "Percent")
        _put("CWAgent",  "mem_used_percent",  dims, ram,                                    "Percent")
        _put("AWS/EC2",  "NetworkIn",         dims, net_in,                                 "Bytes")
        _put("AWS/EC2",  "NetworkOut",        dims, net_out,                                "Bytes")
        _put("AWS/EC2",  "DiskReadBytes",     dims, p["disk_r"] * random.uniform(0.5, 1.5), "Bytes")
        _put("AWS/EC2",  "DiskWriteBytes",    dims, p["disk_w"] * random.uniform(0.5, 1.5), "Bytes")

    logger.info("[injector] EC2 done")


def inject_dynamodb_metrics() -> None:
    for tname, p in DYNAMODB_TABLES.items():
        dims     = [{"Name": "TableName", "Value": tname}]
        get_dims = dims + [{"Name": "Operation", "Value": "GetItem"}]
        put_dims = dims + [{"Name": "Operation", "Value": "PutItem"}]

        rcu = round(max(0.0, _uniform(p["rcu_base"], p["rcu_var"])), 2)
        wcu = round(max(0.0, _uniform(p["wcu_base"], p["wcu_var"])), 2)

        _put("AWS/DynamoDB", "ConsumedReadCapacityUnits",  dims,     rcu,                               "Count")
        _put("AWS/DynamoDB", "ConsumedWriteCapacityUnits", dims,     wcu,                               "Count")
        _put("AWS/DynamoDB", "ThrottledRequests",          dims,     0.0,                               "Count")
        _put("AWS/DynamoDB", "SuccessfulRequestLatency",   get_dims, round(random.uniform(1.5, 4.0), 3), "Milliseconds")
        _put("AWS/DynamoDB", "SuccessfulRequestLatency",   put_dims, round(random.uniform(2.0, 5.5), 3), "Milliseconds")

    logger.info("[injector] DynamoDB done")


def inject_s3_metrics() -> None:
    for bname, p in S3_PROFILES.items():
        std_dims = [{"Name": "BucketName", "Value": bname}, {"Name": "StorageType", "Value": "StandardStorage"}]
        all_dims = [{"Name": "BucketName", "Value": bname}, {"Name": "StorageType", "Value": "AllStorageTypes"}]
        req_dims = [{"Name": "BucketName", "Value": bname}]

        gets = max(0, round(_uniform(p["gets_base"], p["gets_var"])))
        puts = max(0, round(_uniform(p["puts_base"], p["puts_var"])))

        _put("AWS/S3", "BucketSizeBytes",  std_dims, p["size"] * random.uniform(0.99, 1.01), "Bytes")
        _put("AWS/S3", "NumberOfObjects",  all_dims, p["object_count"],                       "Count")
        _put("AWS/S3", "GetRequests",      req_dims, gets,                                    "Count")
        _put("AWS/S3", "PutRequests",      req_dims, puts,                                    "Count")
        _put("AWS/S3", "BytesDownloaded",  req_dims, _uniform(p["dl_base"], p["dl_var"]),     "Bytes")
        _put("AWS/S3", "BytesUploaded",    req_dims, _uniform(p["ul_base"], p["ul_var"]),     "Bytes")

    logger.info("[injector] S3 done")


def inject_all_metrics(**kwargs) -> None:
    logger.info("[injector] Injecting datapoint...")
    inject_ec2_metrics()
    inject_dynamodb_metrics()
    inject_s3_metrics()
    logger.info("[injector] Done")
