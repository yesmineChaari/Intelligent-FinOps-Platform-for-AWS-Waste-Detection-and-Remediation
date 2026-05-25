import logging
import os
import random
from datetime import datetime, timezone

import boto3

logger     = logging.getLogger(__name__)
LOCALSTACK = os.getenv("LOCALSTACK_ENDPOINT", "http://localhost:4566")
REGION     = os.getenv("AWS_REGION", "eu-west-1")

cloudwatch = boto3.client("cloudwatch", endpoint_url=LOCALSTACK, region_name=REGION,
                          aws_access_key_id="test", aws_secret_access_key="test")

# Per-instance profiles matching role and architecture
# i-001 dependant_primary   — high CPU, active network+disk (writes DynamoDB + S3)
# i-002 dependant_secondary — moderate CPU, lighter than primary (failover standby)
# i-003 steady              — low stable CPU (reads DynamoDB, writes S3, sends logs)
# i-004 bursty              — highly variable CPU (writes DynamoDB, reads S3)
# i-005 backup              — minimal CPU, high disk writes (backup job)
# i-006 zombie/steady       — NO metrics → simulates stopped/forgotten instance

EC2_PROFILES = {
    "i-001": {"cpu_base": 58.0, "cpu_var": 12.0, "net": 6_000_000,  "disk_r": 1_500_000, "disk_w": 3_000_000, "ram_base": 65.0, "ram_var": 8.0},
    "i-002": {"cpu_base": 22.0, "cpu_var": 8.0,  "net": 1_800_000,  "disk_r": 400_000,   "disk_w": 600_000,   "ram_base": 40.0, "ram_var": 6.0},
    "i-003": {"cpu_base": 11.0, "cpu_var": 3.0,  "net": 900_000,    "disk_r": 200_000,   "disk_w": 800_000,   "ram_base": 30.0, "ram_var": 5.0},
    "i-004": {"cpu_base": 40.0, "cpu_var": 45.0, "net": 3_500_000,  "disk_r": 800_000,   "disk_w": 1_200_000, "ram_base": 50.0, "ram_var": 20.0},
    "i-005": {"cpu_base": 5.0,  "cpu_var": 2.0,  "net": 300_000,    "disk_r": 100_000,   "disk_w": 8_000_000, "ram_base": 20.0, "ram_var": 4.0},
    # i-006 omitted — zombie, no metrics emitted
}

# r-001 DynamoDB — PROVISIONED 100/100, consumed ~8 RCU / ~5 WCU (over-provisioned)
DYNAMODB_TABLES = {
    "r-001": {"rcu_base": 8.0, "rcu_var": 4.0, "wcu_base": 5.0, "wcu_var": 3.0}
}

# S3 buckets — per-tick request counts and byte volumes matching bucket role
# r-002 primary  — high GET (active reads), moderate PUT
# r-003 logs     — high PUT (log writes), low GET
# r-004 archive  — very low GET and PUT (cold data)
S3_PROFILES = {
    "r-002": {"size": 850_000_000,   "gets_base": 85,  "gets_var": 20,  "puts_base": 8,   "puts_var": 3,   "dl_base": 2_500_000,  "dl_var": 500_000,  "ul_base": 900_000,   "ul_var": 200_000},
    "r-003": {"size": 620_000_000,   "gets_base": 3,   "gets_var": 2,   "puts_base": 36,  "puts_var": 10,  "dl_base": 160_000,    "dl_var": 50_000,   "ul_base": 1_900_000, "ul_var": 400_000},
    "r-004": {"size": 3_200_000_000, "gets_base": 0.2, "gets_var": 0.2, "puts_base": 0.1, "puts_var": 0.1, "dl_base": 10_000,     "dl_var": 5_000,    "ul_base": 25_000,    "ul_var": 10_000},
}


def _put(namespace, metric_name, dims, value, unit):
    cloudwatch.put_metric_data(
        Namespace=namespace,
        MetricData=[{
            "MetricName": metric_name,
            "Dimensions": dims,
            "Timestamp":  datetime.now(timezone.utc),
            "Value":      max(0.0, value),
            "Unit":       unit,
        }]
    )


def inject_ec2_metrics():
    for iid, p in EC2_PROFILES.items():
        dims = [{"Name": "InstanceId", "Value": iid}]
        cpu  = round(min(99.9, max(0.1, p["cpu_base"] + random.uniform(-p["cpu_var"], p["cpu_var"]))), 2)
        ram  = round(min(99.9, max(1.0,  p["ram_base"] + random.uniform(-p["ram_var"], p["ram_var"]))), 2)
        _put("AWS/EC2",  "CPUUtilization",   dims, cpu,                                         "Percent")
        _put("CWAgent",  "mem_used_percent",  dims, ram,                                         "Percent")
        _put("AWS/EC2",  "NetworkIn",         dims, p["net"]    * random.uniform(0.7, 1.3),      "Bytes")
        _put("AWS/EC2",  "NetworkOut",        dims, p["net"]    * random.uniform(0.3, 0.8),      "Bytes")
        _put("AWS/EC2",  "DiskReadBytes",     dims, p["disk_r"] * random.uniform(0.5, 1.5),      "Bytes")
        _put("AWS/EC2",  "DiskWriteBytes",    dims, p["disk_w"] * random.uniform(0.5, 1.5),      "Bytes")
    logger.info("[injector] EC2 done")


def inject_dynamodb_metrics():
    for tname, p in DYNAMODB_TABLES.items():
        dims     = [{"Name": "TableName", "Value": tname}]
        get_dims = dims + [{"Name": "Operation", "Value": "GetItem"}]
        put_dims = dims + [{"Name": "Operation", "Value": "PutItem"}]
        _put("AWS/DynamoDB", "ConsumedReadCapacityUnits",  dims,     round(p["rcu_base"] + random.uniform(-p["rcu_var"], p["rcu_var"]), 2), "Count")
        _put("AWS/DynamoDB", "ConsumedWriteCapacityUnits", dims,     round(p["wcu_base"] + random.uniform(-p["wcu_var"], p["wcu_var"]), 2), "Count")
        _put("AWS/DynamoDB", "ThrottledRequests",          dims,     0.0,                                                                   "Count")
        _put("AWS/DynamoDB", "SuccessfulRequestLatency",   get_dims, round(random.uniform(1.5, 4.0), 3),                                    "Milliseconds")
        _put("AWS/DynamoDB", "SuccessfulRequestLatency",   put_dims, round(random.uniform(2.0, 5.5), 3),                                    "Milliseconds")
    logger.info("[injector] DynamoDB done")


def inject_s3_metrics():
    for bname, p in S3_PROFILES.items():
        std_dims = [{"Name": "BucketName", "Value": bname}, {"Name": "StorageType", "Value": "StandardStorage"}]
        all_dims = [{"Name": "BucketName", "Value": bname}, {"Name": "StorageType", "Value": "AllStorageTypes"}]
        req_dims = [{"Name": "BucketName", "Value": bname}]
        _put("AWS/S3", "BucketSizeBytes",  std_dims, p["size"] * random.uniform(0.99, 1.01),                              "Bytes")
        _put("AWS/S3", "NumberOfObjects",  all_dims, 8,                                                                    "Count")
        _put("AWS/S3", "GetRequests",      req_dims, max(0, round(p["gets_base"] + random.uniform(-p["gets_var"], p["gets_var"]))), "Count")
        _put("AWS/S3", "PutRequests",      req_dims, max(0, round(p["puts_base"] + random.uniform(-p["puts_var"], p["puts_var"]))), "Count")
        _put("AWS/S3", "BytesDownloaded",  req_dims, p["dl_base"] + random.uniform(-p["dl_var"], p["dl_var"]),             "Bytes")
        _put("AWS/S3", "BytesUploaded",    req_dims, p["ul_base"] + random.uniform(-p["ul_var"], p["ul_var"]),             "Bytes")
    logger.info("[injector] S3 done")


def inject_all_metrics(**kwargs):
    logger.info("[injector] Injecting current datapoint...")
    inject_ec2_metrics()
    inject_dynamodb_metrics()
    inject_s3_metrics()
    logger.info("[injector] Done")
