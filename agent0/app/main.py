import logging
import os
from contextlib import asynccontextmanager

import redis
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI

from api import ec2, s3, dynamodb, relationships
from services.discovery import run_discovery
from services.cloudwatch_injector import inject_all_metrics
from services.ec2_metrics import run_ec2_metrics_collection
from services.s3_metrics import run_s3_metrics_collection
from services.dynamodb_metrics import run_dynamodb_metrics_collection
from services.s3_sampler import run_s3_object_sampler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

INGESTION_STREAM = "ingestion_stream"
EVENT_INGESTION_COMPLETE = "ingestion_complete"


def _build_ingestion_complete_payload() -> dict[str, str]:
    payload = {
        "event": EVENT_INGESTION_COMPLETE,
        "status": "completed",
    }
    safe_metadata_sources = (
        ("workspace_key", ("WORKSPACE_KEY", "TERRAFORM_WORKSPACE_KEY")),
        ("account_id", ("ACCOUNT_ID",)),
        ("terraform_repo_url", ("PHASE3_TERRAFORM_REPO_URL",)),
        ("terraform_ref", ("PHASE3_TERRAFORM_REF",)),
        ("terraform_subdir", ("PHASE3_TERRAFORM_SUBDIR",)),
    )
    for field, environment_names in safe_metadata_sources:
        for environment_name in environment_names:
            value = os.environ.get(environment_name)
            if value is not None:
                payload[field] = value
                break
    return payload


def _publish_ingestion_complete() -> bool:
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        logger.warning("[pipeline] REDIS_URL is not set; skipping ingestion_complete publication.")
        return False

    redis_client = None
    try:
        redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
        redis_client.xadd(INGESTION_STREAM, _build_ingestion_complete_payload())
    except Exception:
        logger.warning("[pipeline] Ingestion completed, but Redis event publication failed.")
        return False
    finally:
        if redis_client is not None:
            try:
                redis_client.close()
            except Exception:
                pass

    logger.info("[pipeline] Published ingestion_complete event.")
    return True


def run_full_pipeline():
    """
    Full pipeline run — called every 5 minutes.
      1. discovery      — sync resources from LocalStack into DB
      2. inject_metrics — push synthetic CloudWatch datapoints
      3. collectors     — pull from CloudWatch into DB
      4. s3_sampler     — sample object metadata into DB
    If LocalStack is empty , discovery
    finds nothing and collectors skip. Next tick retries.
    """
    logger.info("[pipeline] Starting full pipeline run...")

    try:
        run_discovery()
    except Exception as e:
        logger.error(f"[pipeline] Discovery failed: {e}")
        return  # no point running collectors if discovery failed

    try:
        inject_all_metrics(ec2_points=12, dynamo_points=12, s3_days=1)
    except Exception as e:
        logger.error(f"[pipeline] Metric injection failed: {e}")

    try:
        run_ec2_metrics_collection()
    except Exception as e:
        logger.error(f"[pipeline] EC2 metrics failed: {e}")

    try:
        run_s3_metrics_collection()
    except Exception as e:
        logger.error(f"[pipeline] S3 metrics failed: {e}")

    try:
        run_dynamodb_metrics_collection()
    except Exception as e:
        logger.error(f"[pipeline] DynamoDB metrics failed: {e}")

    try:
        run_s3_object_sampler()
    except Exception as e:
        logger.error(f"[pipeline] S3 sampler failed: {e}")

    logger.info("[pipeline] Full pipeline run complete")
    _publish_ingestion_complete()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("[startup] Scheduling pipeline every 5 minutes...")

    scheduler.add_job(
        run_full_pipeline,
        "interval",
        minutes=5,
        id="full_pipeline",
        replace_existing=True,
        next_run_time=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),  # run immediately on start
    )

    scheduler.start()
    logger.info("[startup] Scheduler started — pipeline will run now and every 5 min")

    yield

    logger.info("[shutdown] Stopping scheduler...")
    scheduler.shutdown(wait=False)


app = FastAPI(
    title="FinOps Platform",
    description="Cloud cost optimization — discovery, metrics collection, and waste detection",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(ec2.router,           prefix="/api/ec2",          tags=["EC2"])
app.include_router(s3.router,            prefix="/api/s3",           tags=["S3"])
app.include_router(dynamodb.router,      prefix="/api/dynamodb",     tags=["DynamoDB"])
app.include_router(relationships.router, prefix="/api/relationships", tags=["Relationships"])


@app.get("/health")
def health():
    return {"status": "ok"}
