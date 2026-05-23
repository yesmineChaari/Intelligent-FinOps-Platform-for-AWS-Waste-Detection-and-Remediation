"""
Agent 1/2 — Phase 1 + Phase 2 entrypoint.

Wakes up on ingestion_complete from Redis Streams.
Connects to Neon DB, loads rules, runs EC2 and S3 detections.
Phase 1 results stay in memory and are passed to Phase 2.
"""

import asyncio
import asyncpg
import redis.asyncio as aioredis
import os
import json
import logging
import sys
from pathlib import Path

from phase1.loader import load_rules
from phase1.detection import run_phase1
from phase1.s3_detection import run_s3_phase1
from phase2 import run_phase2
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)


def _phase1_metrics_payload(result) -> dict[str, float | int | bool | str]:
    payload: dict[str, float | int | bool | str] = {}
    for field in ("p95_cpu", "p99_cpu", "max_cpu", "p95_ram", "cv"):
        value = getattr(result, field, None)
        if value is not None:
            payload[field] = float(value)

    if getattr(result, "stopped_days", None) is not None:
        payload["stopped_days_since_last_metric"] = int(result.stopped_days)
    elif getattr(getattr(result, "waste_type", None), "value", None) == "zombie":
        payload["stopped_days_since_last_metric"] = "unknown"
        payload["no_metrics_found"] = True

    return payload


def _phase2_metrics_payload(result) -> dict[str, int | bool]:
    payload = {
        "blast_radius_score": int(result.blast_radius_score),
        "relationship_count": int(result.relationship_count),
        "phase2_action_changed": bool(result.phase2_action_changed),
    }
    if getattr(result, "stopped_days", None) is not None:
        payload["stopped_days_since_last_metric"] = int(result.stopped_days)
    return payload


def _s3_metrics_payload(result) -> dict[str, float | int | bool]:
    payload: dict[str, float | int | bool] = {}

    if getattr(result, "has_lifecycle", None) is not None:
        payload["has_lifecycle"] = bool(result.has_lifecycle)
    if getattr(result, "total_requests_30d", None) is not None:
        payload["total_requests_30d"] = float(result.total_requests_30d)
    if getattr(result, "object_count", None) is not None:
        payload["object_count"] = int(result.object_count)
    if getattr(result, "pct_older_90_days", None) is not None:
        payload["pct_older_90_days"] = float(result.pct_older_90_days)
    if getattr(result, "estimated_monthly_savings", None) is not None:
        payload["estimated_monthly_savings"] = float(result.estimated_monthly_savings)

    return payload


async def wait_for_trigger(redis_client: aioredis.Redis) -> None:
    """Block until ingestion_complete arrives on the Redis Stream."""
    log.info("Agent 2 waiting for 'ingestion_complete' on Redis Stream...")
    while True:
        # XREAD with block=0 waits indefinitely until a message arrives
        messages = await redis_client.xread(
            {"ingestion_stream": "$"},
            block=0,
            count=1,
        )
        if messages:
            for stream, entries in messages:
                for entry_id, fields in entries:
                    event = fields.get(b"event", b"").decode()
                    if event == "ingestion_complete":
                        log.info(f"Received ingestion_complete (entry {entry_id}). Triggering Phase 1...")
                        return


async def main():
    # ── Configuration ─────────────────────────────────────────────────────
    neon_db_url = os.environ.get("NEON_DATABASE_URL")
    if not neon_db_url:
        log.error("NEON_DATABASE_URL environment variable is missing. Cannot start.")
        sys.exit(1)
        
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    rules_path = os.environ.get("RULES_PATH", "rules.yaml")

    # ── Load rules at startup — fail fast if malformed ────────────────────
    log.info(f"Loading statistical thresholds from {rules_path}...")
    rules = load_rules(rules_path)
    log.info("Rules loaded and validated successfully.")

    # ── Connect to Redis ───────────────────────────────────────────────────
    redis_client = aioredis.from_url(redis_url, decode_responses=False)

    # ── Wait for Agent 1 to finish ────────────────────────────────────────
    skip_trigger = os.environ.get("SKIP_REDIS_TRIGGER", "").lower() in ("1", "true", "yes")
    if not skip_trigger:
        await wait_for_trigger(redis_client)
    else:
        log.info("SKIP_REDIS_TRIGGER is set; running Phase 1 immediately without waiting on Redis trigger.")

    # ── Connect to Neon DB ────────────────────────────────────────────────
    log.info("Connecting to Neon DB...")
    conn = await asyncpg.connect(neon_db_url)

    try:
        # ── Phase 1 ───────────────────────────────────────────────────────
        log.info("Starting EC2 Phase 1 — Statistical Waste Detection...")
        ec2_results = await run_phase1(conn, rules)

        log.info(f"EC2 Phase 1 complete. {len(ec2_results)} instances flagged for potential action.")
        for r in ec2_results:
            log.info(
                f"  [{r.role}] {r.resource_id} → {r.action.value} "
                f"({r.waste_type.value}) | {r.detection_reason}"
            )

        log.info("Starting S3 Phase 1 — Bucket Waste Detection...")
        s3_results = await run_s3_phase1(conn, rules.s3)
        log.info(f"S3 Phase 1 complete. {len(s3_results)} bucket findings.")
        for r in s3_results:
            log.info(
                f"  [S3] {r.bucket_name} → {r.action.value} "
                f"({r.waste_type.value}) | {r.detection_reason}"
            )

        ec2_output = []
        for r in ec2_results:
            # Update the exclude block in the payload dump
            row = r.model_dump(
            exclude_none=True,
            exclude={
                "p95_cpu", "p99_cpu", "max_cpu", "p95_ram", "cv", "stopped_days",
                "max_network_mbps", "max_disk_mbps", "p99_network_mbps", "p99_disk_mbps" # NEW
            },
        )
            row["metrics"] = _phase1_metrics_payload(r)
            ec2_output.append(row)

        s3_output = []
        for r in s3_results:
            row = r.model_dump(
                exclude_none=True,
                exclude={
                    "has_lifecycle",
                    "total_requests_30d",
                    "object_count",
                    "pct_older_90_days",
                    "estimated_monthly_savings",
                },
            )
            row["metrics"] = _s3_metrics_payload(r)
            s3_output.append(row)

        log.info("Phase 1 Output Payload (JSON):")
        phase1_payload_str = json.dumps({"ec2": ec2_output, "s3": s3_output}, indent=2, default=str)
        print(phase1_payload_str)
        try:
            Path("phase1_output.json").write_text(phase1_payload_str, encoding="utf-8")
            log.info("Phase 1 output written to phase1_output.json")
        except Exception as exc:
            log.warning("Failed to write Phase 1 output file: %s", exc)

        # ── Phase 2 ───────────────────────────────────────────────────────
        log.info("Phase 2 starting — relationship graph guardrails...")
        phase2_results = await run_phase2(conn, ec2_results, rules.phase2)

        log.info(f"Phase 2 complete. {len(phase2_results)} resources evaluated.")
        for r in phase2_results:
            log.info(
                f"  [Phase2] {r.resource_id} phase1_action={r.action} → phase2_action={r.phase2_action} "
                f"| blast={r.blast_radius_score} | {r.phase2_action_reason or 'action kept'} "
                f"| score_expl={r.blast_radius_explanation}"
            )

        phase2_output = []
        for r in phase2_results:
            row = r.model_dump(
                exclude_none=True,
                exclude={"blast_radius_score", "relationship_count", "stopped_days", "phase1_action"},
            )
            row["metrics"] = _phase2_metrics_payload(r)
            phase2_output.append(row)

        log.info("Phase 2 Output Payload (JSON):")
        phase2_payload_str = json.dumps(phase2_output, indent=2, default=str)
        print(phase2_payload_str)
        try:
            Path("phase2_output.json").write_text(phase2_payload_str, encoding="utf-8")
            log.info("Phase 2 output written to phase2_output.json")
        except Exception as exc:
            log.warning("Failed to write Phase 2 output file: %s", exc)

        # ── Phase 3 ───────────────────────────────────────────────────────
        # IMPORTANT: Phase 1/2 outputs above remain unchanged.
        log.info("Phase 3 starting — LLM evaluation...")
        try:
            from phase3.llm_phase3 import run_phase3_llm

            phase3_output = await asyncio.to_thread(
                run_phase3_llm,
                ec2_results,
                phase2_results,
                s3_results,
                os.environ.get("PHASE3_MODEL") or None,
            )

            llm_inputs = [
                {
                    "scenario_type": run.get("scenario_type"),
                    "scenario": run.get("scenario"),
                }
                for run in (phase3_output.get("runs") or [])
            ]
            log.info("Phase 3 LLM Input Scenarios (JSON):")
            print(json.dumps(llm_inputs, indent=2, default=str))

            parsed_outputs = [
                {
                    "scenario_type": run.get("scenario_type"),
                    "parsed": (run.get("llm") or {}).get("parsed"),
                    "parse_error": (run.get("llm") or {}).get("parse_error"),
                }
                for run in (phase3_output.get("runs") or [])
            ]
            log.info("Phase 3 Parsed LLM Output (JSON):")
            print(json.dumps(parsed_outputs, indent=2, default=str))

            log.info("Phase 3 Output Payload (JSON):")
            phase3_payload_str = json.dumps(phase3_output, indent=2, default=str)
            print(phase3_payload_str)
            try:
                Path("phase3_output.json").write_text(phase3_payload_str, encoding="utf-8")
                log.info("Phase 3 output written to phase3_output.json")
            except Exception as exc:
                log.warning("Failed to write Phase 3 output file: %s", exc)
        except Exception as exc:
            log.exception("Phase 3 failed: %s", exc)

    finally:
        await conn.close()
        await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())