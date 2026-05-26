import logging
import os
import random
from datetime import datetime, timezone

import boto3

logger     = logging.getLogger(__name__)
LOCALSTACK = os.getenv("LOCALSTACK_ENDPOINT", "http://localhost:4566")
REGION     = os.getenv("AWS_REGION", "eu-west-1")
DETERMINISTIC_DEMO_METRICS = os.getenv("DETERMINISTIC_DEMO_METRICS", "true").lower() == "true"

if DETERMINISTIC_DEMO_METRICS:
    random.seed(42)

cloudwatch = boto3.client(
    "cloudwatch",
    endpoint_url=LOCALSTACK,
    region_name=REGION,
    aws_access_key_id="test",
    aws_secret_access_key="test",
)

# Expected detection outcomes for the demo fixtures:
#
# EC2:
# - app1-api-primary: dependant_primary idle -> Phase1 DOWNSIZE, Phase2 likely
#   REVIEW due blast radius.
# - app1-api-secondary: dependant_secondary -> SKIP.
# - app1-worker-idle-with-writes: steady idle -> Phase1 STOP, Phase2 DOWNSIZE
#   due writes/logs.
# - app1-worker-oversized-risky: steady oversized -> Phase1 DOWNSIZE, Phase2
#   REVIEW due blast radius.
# - app1-bursty-tag-error: bursty stable CV -> REVIEW tag_error.
# - app1-backup-replica: backup -> SKIP.
# - app1-zombie-isolated: running zombie -> TERMINATE.
# - app2-reporting-primary: dependant_primary idle -> DOWNSIZE.
# - app2-bursty-oversized: bursty oversized -> DOWNSIZE.
# - app2-bursty-clean: bursty clean -> CLEAN.
# - app2-steady-idle-isolated: steady idle -> STOP.
# - app2-steady-oversized-safe: steady oversized -> DOWNSIZE.
# - app2-steady-clean: steady clean -> CLEAN.
# - app2-stopped-zombie: stopped/no metrics -> TERMINATE, seeded by
#   SQL/inventory.
# - app2-stopped-recent: stopped/recent metrics -> REVIEW, seeded by
#   SQL/inventory.
#
# S3:
# - app1-data-bucket: missing_lifecycle, possible storage_mismatch.
# - app1-logs-bucket: missing_lifecycle + storage_mismatch.
# - app1-temp-bucket: missing_lifecycle + abandoned.
# - app2-report-bucket: missing_lifecycle.
# - app2-archive-bucket: missing_lifecycle + storage_mismatch + possible
#   abandoned.
# - app2-clean-bucket: clean, no S3 finding.

# ── EC2 profiles ──────────────────────────────────────────────────────────────
#
# APP-1 detection scenarios:
# app1-api-primary             dependant_primary idle
# app1-api-secondary           dependant_secondary, skipped role
# app1-worker-idle-with-writes steady idle while retaining active IO
# app1-worker-oversized-risky  steady oversized with occasional CPU peaks
# app1-bursty-tag-error        bursty tag_error because CPU is too stable
# app1-backup-replica          backup, skipped role
# app1-zombie-isolated         running zombie with near-zero utilization
#
# APP-2 detection scenarios:
# app2-reporting-primary       dependant_primary idle, safe downsize
# app2-bursty-oversized        bursty oversized with p99 CPU below 30
# app2-bursty-clean            clean bursty instance with high CPU peaks
# app2-steady-idle-isolated    steady idle
# app2-steady-oversized-safe   steady oversized with an occasional CPU peak
# app2-steady-clean            clean steady instance under sustained load
# app2-stopped-zombie requires no metrics or metrics stale by at least 30 days.
# app2-stopped-recent requires its latest metric to be less than 30 days old.
# Stopped metrics must therefore be seeded historically, never emitted live.
#
# Network/disk units: Bytes/s emitted as a single-datapoint proxy.
# The collector aggregates over the window; these values feed p95/p99/max
# calculations in ec2_metrics after collection.

EC2_PROFILES = {
    # P95 CPU < 10 and P95 RAM < 20; active IO prevents zombie detection.
    "app1-api-primary": {
        "cpu_base": 6.0, "cpu_var": 1.5,
        "ram_base": 14.0, "ram_var": 2.0,
        "net": 2_000_000,
        "disk_r": 500_000, "disk_w": 900_000,
    },

    # Skipped role; moderate metrics ensure it is not classified as a zombie first.
    "app1-api-secondary": {
        "cpu_base": 25.0, "cpu_var": 4.0,
        "ram_base": 35.0, "ram_var": 4.0,
        "net": 1_800_000,
        "disk_r": 400_000, "disk_w": 600_000,
    },

    # P95 CPU < 5, P95 RAM < 10, and max CPU < 20 despite write activity.
    "app1-worker-idle-with-writes": {
        "cpu_base": 3.0, "cpu_var": 1.0,
        "ram_base": 7.0, "ram_var": 1.5,
        "net": 900_000,
        "disk_r": 200_000, "disk_w": 2_000_000,
    },

    # Rare peaks push max CPU above 20 while keeping P95 CPU/RAM oversized-safe.
    "app1-worker-oversized-risky": {
        "cpu_base": 14.0, "cpu_var": 4.0,
        "ram_base": 30.0, "ram_var": 3.0,
        "controlled_spike_base": 26.0, "controlled_spike_var": 2.0,
        "controlled_spike_prob": 0.03,
        "net": 1_400_000,
        "disk_r": 450_000, "disk_w": 800_000,
    },

    # Bursty role with CV < 0.5, deliberately producing tag_error.
    "app1-bursty-tag-error": {
        "cpu_base": 12.0, "cpu_var": 1.0,
        "ram_base": 25.0, "ram_var": 2.0,
        "net": 1_100_000,
        "disk_r": 300_000, "disk_w": 500_000,
    },

    # Skipped role; emits moderate non-zombie metrics.
    "app1-backup-replica": {
        "cpu_base": 8.0, "cpu_var": 2.0,
        "ram_base": 20.0, "ram_var": 3.0,
        "net": 700_000,
        "disk_r": 250_000, "disk_w": 1_200_000,
    },

    # Near-zero CPU, network, and disk activity drives running zombie detection.
    "app1-zombie-isolated": {
        "cpu_base": 0.65, "cpu_var": 0.25,
        "ram_base": 4.0, "ram_var": 1.0,
        "net": 50_000,
        "disk_r": 10_000, "disk_w": 10_000,
    },

    # P95 CPU < 10 and P95 RAM < 20 for safe dependant-primary downsize.
    "app2-reporting-primary": {
        "cpu_base": 7.0, "cpu_var": 1.5,
        "ram_base": 15.0, "ram_var": 2.0,
        "net": 1_600_000,
        "disk_r": 450_000, "disk_w": 750_000,
    },

    # Bimodal CPU gives CV >= 0.5 while every possible CPU value remains < 30.
    "app2-bursty-oversized": {
        "cpu_idle_base": 6.0, "cpu_idle_var": 1.5,
        "ram_idle_base": 20.0, "ram_idle_var": 3.0,
        "cpu_spike_base": 26.0, "cpu_spike_var": 2.0,
        "ram_spike_base": 30.0, "ram_spike_var": 3.0,
        "spike_prob": 0.18,
        "net": 2_200_000,
        "disk_r": 600_000, "disk_w": 1_000_000,
    },

    # High bimodal peaks keep CV >= 0.5 and P99 CPU >= 30 for a clean result.
    "app2-bursty-clean": {
        "cpu_idle_base": 6.0, "cpu_idle_var": 1.5,
        "ram_idle_base": 22.0, "ram_idle_var": 3.0,
        "cpu_spike_base": 62.0, "cpu_spike_var": 8.0,
        "ram_spike_base": 55.0, "ram_spike_var": 6.0,
        "spike_prob": 0.15,
        "net": 3_500_000,
        "disk_r": 800_000, "disk_w": 1_200_000,
    },

    # P95 CPU < 5, P95 RAM < 10, and max CPU < 20.
    "app2-steady-idle-isolated": {
        "cpu_base": 3.0, "cpu_var": 1.0,
        "ram_base": 7.0, "ram_var": 1.5,
        "net": 800_000,
        "disk_r": 200_000, "disk_w": 500_000,
    },

    # Rare peaks exceed max CPU 20 while keeping P95 CPU < 20 and P95 RAM < 40.
    "app2-steady-oversized-safe": {
        "cpu_base": 14.0, "cpu_var": 4.0,
        "ram_base": 30.0, "ram_var": 3.0,
        "controlled_spike_base": 26.0, "controlled_spike_var": 2.0,
        "controlled_spike_prob": 0.03,
        "net": 1_500_000,
        "disk_r": 500_000, "disk_w": 900_000,
    },

    # Sustained CPU and RAM usage keeps the steady instance clean.
    "app2-steady-clean": {
        "cpu_base": 35.0, "cpu_var": 5.0,
        "ram_base": 55.0, "ram_var": 5.0,
        "net": 2_500_000,
        "disk_r": 700_000, "disk_w": 1_100_000,
    },
}

# app2-stopped-recent receives its few recent historical datapoints from SQL seed
# only; app2-stopped-zombie must retain no live metric activity.
STOPPED_EC2_NAMES = {"app2-stopped-zombie", "app2-stopped-recent"}

# ── DynamoDB profiles ─────────────────────────────────────────────────────────
# Supporting demo metrics only; current documented detection focuses on EC2/S3.
# app1-db:        provisioned 100/100 RCU/WCU, intentionally consumes ~8/~5.
# app2-warehouse: provisioned 80/80 RCU/WCU, consumes ~12/~7.

DYNAMODB_TABLES = {
    "app1-db": {
        "rcu_base": 8.0,  "rcu_var": 3.0,
        "wcu_base": 5.0,  "wcu_var": 2.0,
    },
    "app2-warehouse": {
        "rcu_base": 12.0, "rcu_var": 3.0,
        "wcu_base": 7.0,  "wcu_var": 2.0,
    },
}

# ── S3 profiles ───────────────────────────────────────────────────────────────
#
# app1-data-bucket     active data bucket: missing_lifecycle; storage_mismatch
#                      can be established by object samples seeded elsewhere.
# app1-logs-bucket     active write-heavy bucket: missing_lifecycle plus
#                      storage_mismatch from separately seeded object samples.
# app1-temp-bucket     abandoned candidate: live request counts remain zero so
#                      30-day GET+PUT total cannot exceed the threshold.
#
# app2-report-bucket   active report bucket: missing_lifecycle only.
# app2-archive-bucket  abandoned candidate: missing_lifecycle and
#                      storage_mismatch; live request counts remain zero.
# app2-clean-bucket    active clean bucket; lifecycle is supplied by Terraform.
#
# Object sample scenarios are DB-level data and are not emitted here.
# BucketSizeBytes uses StandardStorage dimension as required by AWS/S3 schema.

S3_PROFILES = {
    "app1-data-bucket": {
        "object_count": 6,
        "size": 900_000_000,
        "gets_base": 80, "gets_var": 20,
        "puts_base": 8,  "puts_var": 3,
        "dl_base": 2_500_000, "dl_var": 500_000,
        "ul_base": 900_000, "ul_var": 200_000,
    },
    "app1-logs-bucket": {
        "object_count": 5,
        "size": 700_000_000,
        "gets_base": 5,  "gets_var": 2,
        "puts_base": 40, "puts_var": 10,
        "dl_base": 160_000, "dl_var": 50_000,
        "ul_base": 1_900_000, "ul_var": 400_000,
    },
    "app1-temp-bucket": {
        "object_count": 4,
        "size": 250_000_000,
        "gets_base": 0, "gets_var": 0,
        "puts_base": 0, "puts_var": 0,
        "dl_base": 0, "dl_var": 0,
        "ul_base": 0, "ul_var": 0,
    },
    "app2-report-bucket": {
        "object_count": 4,
        "size": 600_000_000,
        "gets_base": 50, "gets_var": 12,
        "puts_base": 5,  "puts_var": 2,
        "dl_base": 1_700_000, "dl_var": 350_000,
        "ul_base": 500_000, "ul_var": 150_000,
    },
    "app2-archive-bucket": {
        "object_count": 7,
        "size": 3_200_000_000,
        "gets_base": 0, "gets_var": 0,
        "puts_base": 0, "puts_var": 0,
        "dl_base": 0, "dl_var": 0,
        "ul_base": 0, "ul_var": 0,
    },
    "app2-clean-bucket": {
        "object_count": 4,
        "size": 150_000_000,
        "gets_base": 30, "gets_var": 8,
        "puts_base": 4,  "puts_var": 2,
        "dl_base": 950_000, "dl_var": 220_000,
        "ul_base": 350_000, "ul_var": 100_000,
    },
}


# ── helpers ───────────────────────────────────────────────────────────────────

_DETERMINISTIC_PROFILE_SAMPLE_COUNTS = {}


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
    if DETERMINISTIC_DEMO_METRICS:
        return base
    return base + random.uniform(-var, var)


def _profile_spikes(profile: dict, probability: float) -> bool:
    if not DETERMINISTIC_DEMO_METRICS:
        return random.random() < probability
    if probability <= 0:
        return False

    key = id(profile)
    sample_index = _DETERMINISTIC_PROFILE_SAMPLE_COUNTS.get(key, 0)
    _DETERMINISTIC_PROFILE_SAMPLE_COUNTS[key] = sample_index + 1
    interval = max(1, round(1.0 / probability))
    return sample_index % interval == 0


def _profile_cpu_ram(profile: dict) -> tuple:
    if "spike_prob" in profile:
        if _profile_spikes(profile, profile["spike_prob"]):
            cpu = _uniform(profile["cpu_spike_base"], profile["cpu_spike_var"])
            ram = _uniform(profile["ram_spike_base"], profile["ram_spike_var"])
        else:
            cpu = _uniform(profile["cpu_idle_base"], profile["cpu_idle_var"])
            ram = _uniform(profile["ram_idle_base"], profile["ram_idle_var"])
    elif "controlled_spike_prob" in profile:
        if _profile_spikes(profile, profile["controlled_spike_prob"]):
            cpu = _uniform(profile["controlled_spike_base"], profile["controlled_spike_var"])
        else:
            cpu = _uniform(profile["cpu_base"], profile["cpu_var"])
        ram = _uniform(profile["ram_base"], profile["ram_var"])
    else:
        cpu = _uniform(profile["cpu_base"], profile["cpu_var"])
        ram = _uniform(profile["ram_base"], profile["ram_var"])

    cpu = round(min(99.9, max(0.1, cpu)), 2)
    ram = round(min(99.9, max(1.0, ram)), 2)
    return cpu, ram


# ── per-service injectors ─────────────────────────────────────────────────────

def inject_ec2_metrics() -> None:
    for iid, p in EC2_PROFILES.items():
        if iid in STOPPED_EC2_NAMES:
            continue

        dims = [{"Name": "InstanceId", "Value": iid}]
        cpu, ram = _profile_cpu_ram(p)

        net_in  = _uniform(p["net"],        p["net"] * 0.3)
        net_out = _uniform(p["net"] * 0.55, p["net"] * 0.25)

        _put("AWS/EC2",  "CPUUtilization",   dims, cpu,                                    "Percent")
        _put("CWAgent",  "mem_used_percent",  dims, ram,                                    "Percent")
        _put("AWS/EC2",  "NetworkIn",         dims, net_in,                                 "Bytes")
        _put("AWS/EC2",  "NetworkOut",        dims, net_out,                                "Bytes")
        _put("AWS/EC2",  "DiskReadBytes",     dims, _uniform(p["disk_r"], p["disk_r"] * 0.5), "Bytes")
        _put("AWS/EC2",  "DiskWriteBytes",    dims, _uniform(p["disk_w"], p["disk_w"] * 0.5), "Bytes")

    logger.info("[injector] EC2 done")


def inject_dynamodb_metrics() -> None:
    for tname, p in DYNAMODB_TABLES.items():
        dims     = [{"Name": "TableName", "Value": tname}]
        get_dims = dims + [{"Name": "Operation", "Value": "GetItem"}]
        put_dims = dims + [{"Name": "Operation", "Value": "PutItem"}]

        rcu = round(max(0.0, _uniform(p["rcu_base"], p["rcu_var"])), 2)
        wcu = round(max(0.0, _uniform(p["wcu_base"], p["wcu_var"])), 2)

        _put("AWS/DynamoDB", "ConsumedReadCapacityUnits",  dims,     rcu,                                "Count")
        _put("AWS/DynamoDB", "ConsumedWriteCapacityUnits", dims,     wcu,                                "Count")
        _put("AWS/DynamoDB", "ThrottledRequests",          dims,     0.0,                                "Count")
        _put("AWS/DynamoDB", "SuccessfulRequestLatency",   get_dims, round(_uniform(2.75, 1.25), 3),     "Milliseconds")
        _put("AWS/DynamoDB", "SuccessfulRequestLatency",   put_dims, round(_uniform(3.75, 1.75), 3),     "Milliseconds")

    logger.info("[injector] DynamoDB done")


def inject_s3_metrics() -> None:
    for bname, p in S3_PROFILES.items():
        std_dims = [{"Name": "BucketName", "Value": bname}, {"Name": "StorageType", "Value": "StandardStorage"}]
        all_dims = [{"Name": "BucketName", "Value": bname}, {"Name": "StorageType", "Value": "AllStorageTypes"}]
        req_dims = [{"Name": "BucketName", "Value": bname}]

        gets = max(0, round(_uniform(p["gets_base"], p["gets_var"])))
        puts = max(0, round(_uniform(p["puts_base"], p["puts_var"])))

        _put("AWS/S3", "BucketSizeBytes",  std_dims, _uniform(p["size"], p["size"] * 0.01), "Bytes")
        _put("AWS/S3", "NumberOfObjects",  all_dims, p["object_count"],                      "Count")
        _put("AWS/S3", "GetRequests",      req_dims, gets,                                   "Count")
        _put("AWS/S3", "PutRequests",      req_dims, puts,                                   "Count")
        _put("AWS/S3", "BytesDownloaded",  req_dims, _uniform(p["dl_base"], p["dl_var"]),    "Bytes")
        _put("AWS/S3", "BytesUploaded",    req_dims, _uniform(p["ul_base"], p["ul_var"]),    "Bytes")

    logger.info("[injector] S3 done")


def inject_all_metrics(**kwargs) -> None:
    logger.info("[injector] Injecting datapoint...")
    inject_ec2_metrics()
    inject_dynamodb_metrics()
    inject_s3_metrics()
    logger.info("[injector] Done")
