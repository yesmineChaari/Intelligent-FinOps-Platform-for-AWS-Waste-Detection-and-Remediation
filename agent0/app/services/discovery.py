import logging
import os

import boto3
from botocore.exceptions import ClientError
from core.db import get_db

logger = logging.getLogger(__name__)

LOCALSTACK = os.getenv("LOCALSTACK_ENDPOINT", "http://localhost:4566")
REGION = os.getenv("AWS_REGION", "eu-west-1")

ec2_client = boto3.client(
    "ec2",
    endpoint_url=LOCALSTACK,
    region_name=REGION,
    aws_access_key_id="test",
    aws_secret_access_key="test",
)
s3_client = boto3.client(
    "s3",
    endpoint_url=LOCALSTACK,
    region_name=REGION,
    aws_access_key_id="test",
    aws_secret_access_key="test",
)
ddb_client = boto3.client(
    "dynamodb",
    endpoint_url=LOCALSTACK,
    region_name=REGION,
    aws_access_key_id="test",
    aws_secret_access_key="test",
)

RELATIONSHIP_TAG_MAP = {
    "WritesTo": "writes_to",
    "ReadsFrom": "reads_from",
    "SendsLogsTo": "sends_logs_to",
    "ReplicatesTo": "replicates_to",
    "FailoverFor": "failover_for",
    "BackupOf": "backup_of",
    "RoutesTrafficTo": "routes_traffic_to",
    "LoadBalancesTo": "load_balances_to",
    "SendsMessagesTo": "sends_messages_to",
    "ReadsFromQueue": "reads_from_queue",
    "MonitoredBy": "monitored_by",
}


def _tags(raw):
    return {t["Key"]: t["Value"] for t in (raw or [])}


def _upsert_resource(cur, name, rtype):
    cur.execute(
        "INSERT INTO resources (name, resource_type) VALUES (%s,%s) ON CONFLICT (name) DO NOTHING",
        (name, rtype),
    )
    cur.execute("SELECT id FROM resources WHERE name=%s", (name,))
    return cur.fetchone()[0]


def _upsert_app_group(cur, group_name, resource_id):
    if not group_name:
        return
    cur.execute(
        "INSERT INTO app_groups (group_name) VALUES (%s) ON CONFLICT (group_name) DO NOTHING",
        (group_name,),
    )
    cur.execute("SELECT id FROM app_groups WHERE group_name=%s", (group_name,))
    group_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO app_group_members (group_id, resource_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
        (group_id, resource_id),
    )


def _upsert_relationships(cur, resource_id, tags):
    managed_relationship_types = list(RELATIONSHIP_TAG_MAP.values())
    cur.execute(
        """
        DELETE FROM resource_relationships
        WHERE resource_id = %s
          AND relationship_type = ANY(%s::relationship_type_enum[])
        """,
        (resource_id, managed_relationship_types),
    )

    cur.execute(
        """
        SELECT related_resource_id, relationship_type
        FROM resource_relationships
        WHERE resource_id = %s
        LIMIT 1
        """,
        (resource_id,),
    )
    existing_source_relationship = cur.fetchone()
    if existing_source_relationship:
        logger.warning(
            "[discovery] Relationship source '%s' already has an unmanaged relationship "
            "to resource '%s' with type '%s' - skipping managed relationships",
            resource_id,
            existing_source_relationship[0],
            existing_source_relationship[1],
        )
        return

    saw_relationship_tag = False
    for tag_key, rel_type in RELATIONSHIP_TAG_MAP.items():
        raw = tags.get(tag_key, "").strip()
        if not raw:
            continue
        saw_relationship_tag = True

        cur.execute(
            """
            SELECT resource_id, related_resource_id
            FROM resource_relationships
            WHERE relationship_type = %s::relationship_type_enum
            LIMIT 1
            """,
            (rel_type,),
        )
        existing_type_relationship = cur.fetchone()
        if existing_type_relationship:
            logger.warning(
                "[discovery] Relationship type '%s' from tag '%s' is already used "
                "by source '%s' to target '%s' - skipping",
                rel_type,
                tag_key,
                existing_type_relationship[0],
                existing_type_relationship[1],
            )
            continue

        for related_name in [n.strip() for n in raw.split(",") if n.strip()]:
            cur.execute("SELECT id FROM resources WHERE name=%s", (related_name,))
            row = cur.fetchone()
            if not row:
                logger.warning(
                    "[discovery] Relationship target '%s' from tag '%s' not found - skipping",
                    related_name,
                    tag_key,
                )
                continue

            related_resource_id = row[0]
            cur.execute(
                """
                SELECT resource_id, relationship_type
                FROM resource_relationships
                WHERE related_resource_id = %s
                LIMIT 1
                """,
                (related_resource_id,),
            )
            existing_target_relationship = cur.fetchone()
            if existing_target_relationship:
                logger.warning(
                    "[discovery] Relationship target '%s' from tag '%s' is already used "
                    "by source '%s' with type '%s' - skipping",
                    related_name,
                    tag_key,
                    existing_target_relationship[0],
                    existing_target_relationship[1],
                )
                continue

            cur.execute("SAVEPOINT relationship_insert")
            try:
                cur.execute(
                    """
                    INSERT INTO resource_relationships (resource_id, related_resource_id, relationship_type)
                    VALUES (%s,%s,%s)
                    ON CONFLICT DO NOTHING
                    """,
                    (resource_id, related_resource_id, rel_type),
                )
                inserted = cur.rowcount
            except Exception as e:
                cur.execute("ROLLBACK TO SAVEPOINT relationship_insert")
                cur.execute("RELEASE SAVEPOINT relationship_insert")
                logger.warning(
                    "[discovery] Relationship insert from source '%s' to target '%s' "
                    "with type '%s' failed - skipping: %s",
                    resource_id,
                    related_name,
                    rel_type,
                    e,
                )
                return

            cur.execute("RELEASE SAVEPOINT relationship_insert")
            if inserted == 0:
                logger.warning(
                    "[discovery] Relationship from source '%s' to target '%s' "
                    "with type '%s' conflicted - skipping",
                    resource_id,
                    related_name,
                    rel_type,
                )
                continue
            return

    if saw_relationship_tag:
        logger.warning(
            "[discovery] No valid managed relationship inserted for source '%s'",
            resource_id,
        )


def _bucket_has_lifecycle(bucket_name: str) -> bool:
    try:
        lifecycle = s3_client.get_bucket_lifecycle_configuration(Bucket=bucket_name)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        error_message = e.response.get("Error", {}).get("Message", "")
        status_code = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if error_code in {"NoSuchLifecycleConfiguration", "NoSuchLifecycle"}:
            return False
        if status_code == 404 and "lifecycle" in error_message.lower():
            return False
        logger.warning(f"[discovery] Cannot read lifecycle for bucket '{bucket_name}': {e}")
        return False
    except Exception as e:
        logger.warning(f"[discovery] Cannot read lifecycle for bucket '{bucket_name}': {e}")
        return False

    return bool(lifecycle.get("Rules"))


def _delete_removed_resources(cur, live_names: set, resource_type: str):
    cur.execute(
        "SELECT id, name FROM resources WHERE resource_type=%s",
        (resource_type,),
    )
    db_resources = cur.fetchall()

    for db_id, db_name in db_resources:
        if db_name not in live_names:
            logger.info(f"[discovery] {db_name} no longer in infrastructure - deleting from DB")
            # Cascades handle: ec2_instances/s3_instances/dynamodb_instances,
            # ec2_metrics/s3_metrics/dynamodb_metrics, s3_object_samples,
            # resource_relationships, app_group_members, waste, s3_waste
            cur.execute("DELETE FROM resources WHERE id=%s", (db_id,))


def _discover_ec2(cur):
    live_names = set()
    for reservation in ec2_client.describe_instances()["Reservations"]:
        for inst in reservation["Instances"]:
            tags = _tags(inst.get("Tags", []))
            name = tags.get("Name")
            if not name:
                continue
            live_names.add(name)
            resource_id = _upsert_resource(cur, name, "ec2")
            os_type = "windows" if tags.get("Platform", "linux").lower() == "windows" else "linux"
            cur.execute(
                """
                INSERT INTO ec2_instances
                    (resource_id, name, instance_type, region, status, launched_at, role, environment, team, os)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (resource_id) DO UPDATE SET
                    status=EXCLUDED.status,
                    launched_at=EXCLUDED.launched_at,
                    instance_type=EXCLUDED.instance_type
                """,
                (
                    resource_id,
                    name,
                    inst.get("InstanceType"),
                    REGION,
                    inst["State"]["Name"],
                    inst.get("LaunchTime"),
                    tags.get("Role"),
                    tags.get("Environment"),
                    tags.get("Team"),
                    os_type,
                ),
            )
            _upsert_app_group(cur, tags.get("AppGroup"), resource_id)
            _upsert_relationships(cur, resource_id, tags)

    _delete_removed_resources(cur, live_names, "ec2")
    logger.info(f"[discovery] EC2 done - {len(live_names)} live instances")


def _discover_s3(cur):
    live_names = set()
    for bucket in s3_client.list_buckets().get("Buckets", []):
        name = bucket["Name"]
        live_names.add(name)
        resource_id = _upsert_resource(cur, name, "s3")
        try:
            tags = _tags(s3_client.get_bucket_tagging(Bucket=name).get("TagSet", []))
        except Exception:
            tags = {}
        obj_count, size = 0, 0
        try:
            for page in s3_client.get_paginator("list_objects_v2").paginate(Bucket=name):
                for obj in page.get("Contents", []):
                    obj_count += 1
                    size += obj.get("Size", 0)
        except Exception:
            pass
        has_lifecycle = _bucket_has_lifecycle(name)
        cur.execute(
            """
            INSERT INTO s3_instances
                (resource_id, name, region, status, launched_at, role, environment, team, creation_date, object_count, size_bytes, has_lifecycle)
            VALUES (%s,%s,%s,'active',%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (resource_id) DO UPDATE SET
                status=EXCLUDED.status,
                launched_at=EXCLUDED.launched_at,
                role=EXCLUDED.role,
                environment=EXCLUDED.environment,
                team=EXCLUDED.team,
                creation_date=EXCLUDED.creation_date,
                object_count=EXCLUDED.object_count,
                size_bytes=EXCLUDED.size_bytes,
                has_lifecycle=EXCLUDED.has_lifecycle
            """,
            (
                resource_id,
                name,
                REGION,
                bucket.get("CreationDate"),
                tags.get("Role"),
                tags.get("Environment"),
                tags.get("Team"),
                bucket.get("CreationDate"),
                obj_count,
                size,
                has_lifecycle,
            ),
        )
        _upsert_app_group(cur, tags.get("AppGroup"), resource_id)

    _delete_removed_resources(cur, live_names, "s3")
    logger.info(f"[discovery] S3 done - {len(live_names)} live buckets")


def _discover_dynamodb(cur):
    live_names = set()
    for page in ddb_client.get_paginator("list_tables").paginate():
        for tname in page["TableNames"]:
            live_names.add(tname)
            desc = ddb_client.describe_table(TableName=tname)["Table"]
            tags = _tags(ddb_client.list_tags_of_resource(ResourceArn=desc["TableArn"]).get("Tags", []))
            rid = _upsert_resource(cur, tname, "dynamodb")
            prov = desc.get("ProvisionedThroughput", {})
            cur.execute(
                """
                INSERT INTO dynamodb_instances
                    (resource_id, name, region, status, launched_at, role, environment, team, read_capacity, write_capacity, billing_mode)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (resource_id) DO UPDATE SET
                    status=EXCLUDED.status,
                    read_capacity=EXCLUDED.read_capacity,
                    write_capacity=EXCLUDED.write_capacity
                """,
                (
                    rid,
                    tname,
                    REGION,
                    desc.get("TableStatus", "ACTIVE"),
                    desc.get("CreationDateTime"),
                    tags.get("Role"),
                    tags.get("Environment"),
                    tags.get("Team"),
                    prov.get("ReadCapacityUnits", 0),
                    prov.get("WriteCapacityUnits", 0),
                    desc.get("BillingModeSummary", {}).get("BillingMode", "PROVISIONED"),
                ),
            )
            _upsert_app_group(cur, tags.get("AppGroup"), rid)
            _upsert_relationships(cur, rid, tags)

    _delete_removed_resources(cur, live_names, "dynamodb")
    logger.info(f"[discovery] DynamoDB done - {len(live_names)} live tables")


def run_discovery():
    logger.info("[discovery] Starting...")
    with get_db() as conn:
        with conn.cursor() as cur:
            _discover_ec2(cur)
            _discover_s3(cur)
            _discover_dynamodb(cur)
    logger.info("[discovery] Complete")
