from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

import redis.asyncio as aioredis

from agent1.phase1.detection import run_phase1
from agent1.phase1.loader import load_rules
from agent1.phase1.s3_detection import run_s3_phase1
from agent1.phase2 import run_phase2
from shared.db import connect_database
from shared.events import (
    EVENT_DETERMINISTIC_COMPLETE,
    EVENT_INGESTION_COMPLETE,
    INGESTION_STREAM,
    OPTIMIZATION_STREAM,
    publish_event,
    wait_for_event,
)
from shared.persistence import (
    complete_optimization_run,
    save_phase1_outputs,
    save_phase2_outputs,
    start_optimization_run,
)
from shared.settings import env_flag, env_str


log = logging.getLogger(__name__)

_REDIS_DEFAULT = "redis://localhost:6379"
_SAFE_TRIGGER_FIELDS = ("workspace_key", "workspace_id", "account_id")


def _deterministic_event_payload(trigger_payload: dict[str, str], run_id: int) -> dict[str, object]:
    payload: dict[str, object] = {
        "run_id": run_id,
        "status": "phase2_completed",
    }
    for field in _SAFE_TRIGGER_FIELDS:
        if trigger_payload.get(field) is not None:
            payload[field] = trigger_payload[field]

    terraform_fields = (
        ("terraform_repo_url", "repo_url", "PHASE3_TERRAFORM_REPO_URL"),
        ("terraform_ref", "repo_ref", "PHASE3_TERRAFORM_REF"),
        ("terraform_subdir", "repo_subdir", "PHASE3_TERRAFORM_SUBDIR"),
    )
    for field, fallback_field, environment_field in terraform_fields:
        value = (
            trigger_payload.get(field)
            or trigger_payload.get(fallback_field)
            or env_str(environment_field)
        )
        if value is not None:
            payload[field] = value
    return payload


async def _close_if_supported(resource: Any) -> None:
    if resource is None:
        return
    close = getattr(resource, "aclose", None) or getattr(resource, "close", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result


async def main() -> int:
    database_url = env_str("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is required")

    redis_url = env_str("REDIS_URL", _REDIS_DEFAULT) or _REDIS_DEFAULT
    rules_path = env_str("RULES_PATH", "rules.yaml") or "rules.yaml"
    skip_wait = env_flag("AGENT1_SKIP_WAIT")

    rules = load_rules(rules_path)
    redis_client = aioredis.from_url(redis_url, decode_responses=False)
    conn = None
    run_id: int | None = None

    try:
        if skip_wait:
            trigger_payload: dict[str, str] = {}
        else:
            trigger_payload = await wait_for_event(
                redis_client,
                INGESTION_STREAM,
                EVENT_INGESTION_COMPLETE,
            )

        conn = await connect_database(database_url)
        workspace_key = trigger_payload.get("workspace_key") or trigger_payload.get("workspace_id")
        run_id = await start_optimization_run(
            conn,
            workspace_key=workspace_key,
            trigger_context=trigger_payload,
        )

        ec2_results = await run_phase1(conn, rules)
        s3_results = await run_s3_phase1(conn, rules.s3)
        await save_phase1_outputs(conn, run_id, ec2_results, s3_results)

        phase2_results = await run_phase2(conn, ec2_results, rules.phase2)
        await save_phase2_outputs(conn, run_id, phase2_results)
        await complete_optimization_run(conn, run_id, status="phase2_completed")

        await publish_event(
            redis_client,
            OPTIMIZATION_STREAM,
            EVENT_DETERMINISTIC_COMPLETE,
            _deterministic_event_payload(trigger_payload, run_id),
        )
        return run_id
    except Exception as exc:
        if conn is not None and run_id is not None:
            try:
                await complete_optimization_run(
                    conn,
                    run_id,
                    status="failed",
                    error_message=str(exc),
                )
            except Exception:
                log.exception("Failed to mark deterministic optimization run as failed")
        raise
    finally:
        await _close_if_supported(conn)
        await _close_if_supported(redis_client)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(main())
