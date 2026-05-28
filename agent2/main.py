from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

import redis.asyncio as aioredis

from agent2.phase3.llm_phase3 import run_phase3_llm
from shared.db import connect_database
from shared.events import (
    EVENT_DETERMINISTIC_COMPLETE,
    EVENT_PHASE3_COMPLETE,
    EVENT_PHASE3_FAILED,
    OPTIMIZATION_STREAM,
    publish_event,
    wait_for_event,
)
from shared.persistence import (
    complete_optimization_run,
    load_phase1_ec2_outputs,
    load_phase1_s3_outputs,
    load_phase2_ec2_outputs,
    save_phase3_outputs,
    update_optimization_run_status,
)
from shared.settings import env_str


log = logging.getLogger(__name__)

_REDIS_DEFAULT = "redis://localhost:6379"
_SAFE_FAILURE_MESSAGE = "Phase 3 worker failed"


def _parse_run_id(value: object) -> int:
    if value is None or str(value).strip() == "":
        raise ValueError("run_id is required")
    try:
        return int(str(value).strip())
    except ValueError as exc:
        raise ValueError("run_id must be an integer") from exc


def _build_terraform_source(event_payload: dict[str, str]) -> dict[str, str | None]:
    return {
        "repo_url": (
            event_payload.get("terraform_repo_url")
            or event_payload.get("repo_url")
            or env_str("PHASE3_TERRAFORM_REPO_URL")
        ),
        "ref": (
            event_payload.get("terraform_ref")
            or event_payload.get("repo_ref")
            or env_str("PHASE3_TERRAFORM_REF")
        ),
        "subdir": (
            event_payload.get("terraform_subdir")
            or event_payload.get("repo_subdir")
            or env_str("PHASE3_TERRAFORM_SUBDIR")
        ),
    }


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
    database_url = env_str("DATABASE_URL") or env_str("NEON_DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL or NEON_DATABASE_URL environment variable is required")

    redis_url = env_str("REDIS_URL", _REDIS_DEFAULT) or _REDIS_DEFAULT
    manual_run_id = env_str("AGENT2_RUN_ID")
    model_key = env_str("PHASE3_MODEL") or None

    redis_client = aioredis.from_url(redis_url, decode_responses=False)
    conn = None
    run_id: int | None = None

    try:
        if manual_run_id and manual_run_id.strip():
            event_payload: dict[str, str] = {}
            run_id = _parse_run_id(manual_run_id)
        else:
            event_payload = await wait_for_event(
                redis_client,
                OPTIMIZATION_STREAM,
                EVENT_DETERMINISTIC_COMPLETE,
            )
            run_id = _parse_run_id(event_payload.get("run_id"))

        conn = await connect_database(database_url)
        await update_optimization_run_status(conn, run_id, "running_phase3")
        ec2_phase1_results = await load_phase1_ec2_outputs(conn, run_id)
        ec2_phase2_results = await load_phase2_ec2_outputs(conn, run_id)
        evaluate_s3 = env_str("PHASE3_EVALUATE_S3", "1").strip().lower() not in {"0", "false", "no"}
        s3_phase1_results = await load_phase1_s3_outputs(conn, run_id) if evaluate_s3 else []
        if not evaluate_s3:
            log.info("S3 evaluation disabled (PHASE3_EVALUATE_S3=0)")

        phase3_output = await asyncio.to_thread(
            run_phase3_llm,
            ec2_phase1_results,
            ec2_phase2_results,
            s3_phase1_results,
            model_key=model_key,
            terraform_source=_build_terraform_source(event_payload),
        )

        # LLM calls can take several minutes — reconnect in case the DB connection timed out
        await _close_if_supported(conn)
        conn = await connect_database(database_url)

        await save_phase3_outputs(
            conn,
            run_id,
            phase3_output,
            phase2_results=ec2_phase2_results,
            s3_results=s3_phase1_results,
        )
        await complete_optimization_run(conn, run_id, status="completed")
        try:
            await publish_event(
                redis_client,
                OPTIMIZATION_STREAM,
                EVENT_PHASE3_COMPLETE,
                {"run_id": run_id, "status": "completed"},
            )
        except Exception:
            log.warning("Redis unavailable — phase3_complete event not published (run still completed)")
        return run_id
    except Exception:
        if conn is not None and run_id is not None:
            try:
                await update_optimization_run_status(
                    conn,
                    run_id,
                    "phase3_failed",
                    error_message=_SAFE_FAILURE_MESSAGE,
                )
            except Exception:
                log.error("Failed to mark Phase 3 optimization run as failed")
        try:
            payload: dict[str, object] = {
                "status": "phase3_failed",
                "error_message": _SAFE_FAILURE_MESSAGE,
            }
            if run_id is not None:
                payload["run_id"] = run_id
            await publish_event(
                redis_client,
                OPTIMIZATION_STREAM,
                EVENT_PHASE3_FAILED,
                payload,
            )
        except Exception:
            log.error("Failed to publish Phase 3 failure event")
        raise
    finally:
        await _close_if_supported(conn)
        await _close_if_supported(redis_client)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(main())
