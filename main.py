"""
Agent 2 — Phase 1 entrypoint.

Wakes up on ingestion_complete from Redis Streams.
Connects to Neon DB, loads rules, runs detection, returns results in memory.
No database writes happen in Phase 1 — results are passed directly to Phase 2.
"""

import asyncio
import asyncpg
import redis.asyncio as aioredis
import os
import json
import logging
import sys

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
    findings_limit = 10

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
        log.info("Starting Phase 1 — Statistical Waste Detection...")
        results = await run_phase1(conn, rules)

        log.info(f"Phase 1 complete. {len(results)} instances flagged for potential action.")
        for r in results:
            log.info(
                f"  [{r.role}] {r.resource_id} → {r.action.value} "
                f"({r.waste_type.value}) | {r.detection_reason}"
            )

        # Phase 1 results stay in memory — passed directly to Phase 2
        # Phase 2 will run here in the same process, receiving `results`
        
        # Clean JSON dump: exclude_none=True prevents logging empty statistical fields 
        # (e.g., CV for steady instances) to keep logs highly readable.
        output = []
        for r in results:
            row = r.model_dump(
                exclude_none=True,
                exclude={"p95_cpu", "p99_cpu", "max_cpu", "p95_ram", "cv", "stopped_days"},
            )
            row["metrics"] = _phase1_metrics_payload(r)
            output.append(row)
        log.info("Phase 1 Output Payload (JSON):")
        ec2_output = output[:findings_limit]
        print(json.dumps(ec2_output, indent=2, default=str))

        # ── Phase 1 (S3) ──────────────────────────────────────────────────
        log.info("Starting S3 Phase 1 — Bucket Waste Detection...")
        s3_results = await run_s3_phase1(conn, rules.s3)

        log.info("S3 Phase 1 complete. %s bucket findings generated.", len(s3_results))
        s3_output = [r.model_dump(exclude_none=True) for r in s3_results]
        s3_output = s3_output[:findings_limit]
        log.info("S3 Phase 1 Output Payload (JSON):")
        print(json.dumps(s3_output, indent=2, default=str))

        # ── Phase 2 ───────────────────────────────────────────────────────
        log.info("Phase 2 starting — relationship graph guardrails...")
        phase2_results = await run_phase2(conn, results, rules.phase2)

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
        print(json.dumps(phase2_output, indent=2, default=str))

    finally:
        await conn.close()
        await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())