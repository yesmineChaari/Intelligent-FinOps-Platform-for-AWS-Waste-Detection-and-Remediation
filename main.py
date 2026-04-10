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
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)


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
        log.info("Starting Phase 1 — Statistical Waste Detection...")
        results = await run_phase1(conn, rules)

        log.info(f"Phase 1 complete. {len(results)} instances flagged for potential action.")
        for r in results:
            log.info(
                f"  [{r.role}] {r.instance_id} → {r.action.value} "
                f"({r.waste_type.value}) | {r.detection_reason}"
            )

        # Phase 1 results stay in memory — passed directly to Phase 2
        # Phase 2 will run here in the same process, receiving `results`
        
        # Clean JSON dump: exclude_none=True prevents logging empty statistical fields 
        # (e.g., CV for steady instances) to keep logs highly readable.
        output = [r.model_dump(exclude_none=True) for r in results]
        log.info("Phase 1 Output Payload (JSON):")
        print(json.dumps(output, indent=2, default=str))

        return results

    finally:
        await conn.close()
        await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())