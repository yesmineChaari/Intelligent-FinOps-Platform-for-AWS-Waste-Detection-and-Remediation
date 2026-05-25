"""Entrypoint tests for the deterministic Agent1 worker.

Using mocks for Redis, Postgres, and phase execution, these tests verify skip
mode and event-wait mode, execution of Phase 1 and Phase 2 only, ordered run
status transitions, forwarding of safe trigger metadata, publication of
``deterministic_complete``, safe failure status recording, resource cleanup,
and the absence of Phase 3 or benchmarking imports.
"""

import ast
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

import agent1.main as agent1_main
from shared.events import (
    EVENT_DETERMINISTIC_COMPLETE,
    EVENT_INGESTION_COMPLETE,
    INGESTION_STREAM,
    OPTIMIZATION_STREAM,
)


class FakeConnection:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeRedis:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class TestAgent1Entrypoint(unittest.IsolatedAsyncioTestCase):
    async def test_skip_wait_runs_deterministic_phases_and_closes_connections(self) -> None:
        conn = FakeConnection()
        redis_client = FakeRedis()
        rules = SimpleNamespace(s3="s3-rules", phase2="phase2-rules")
        wait_for_event = AsyncMock()
        connect_database = AsyncMock(return_value=conn)
        start_run = AsyncMock(return_value=77)
        run_phase1 = AsyncMock(return_value=["ec2-result"])
        run_s3_phase1 = AsyncMock(return_value=["s3-result"])
        save_phase1 = AsyncMock()
        run_phase2 = AsyncMock(return_value=["phase2-result"])
        save_phase2 = AsyncMock()
        update_status = AsyncMock()
        publish_event = AsyncMock(return_value="9-0")

        with (
            patch.dict(
                os.environ,
                {
                    "DATABASE_URL": "postgresql://test",
                    "REDIS_URL": "redis://unit-test:6379",
                    "RULES_PATH": "unit-rules.yaml",
                    "AGENT1_SKIP_WAIT": "true",
                },
                clear=True,
            ),
            patch.object(agent1_main, "load_rules", Mock(return_value=rules)) as load_rules,
            patch.object(agent1_main.aioredis, "from_url", return_value=redis_client) as from_url,
            patch.object(agent1_main, "wait_for_event", wait_for_event),
            patch.object(agent1_main, "connect_database", connect_database),
            patch.object(agent1_main, "start_optimization_run", start_run),
            patch.object(agent1_main, "run_phase1", run_phase1),
            patch.object(agent1_main, "run_s3_phase1", run_s3_phase1),
            patch.object(agent1_main, "save_phase1_outputs", save_phase1),
            patch.object(agent1_main, "run_phase2", run_phase2),
            patch.object(agent1_main, "save_phase2_outputs", save_phase2),
            patch.object(agent1_main, "update_optimization_run_status", update_status),
            patch.object(agent1_main, "publish_event", publish_event),
        ):
            run_id = await agent1_main.main()

        self.assertEqual(run_id, 77)
        load_rules.assert_called_once_with("unit-rules.yaml")
        from_url.assert_called_once_with("redis://unit-test:6379", decode_responses=False)
        wait_for_event.assert_not_awaited()
        connect_database.assert_awaited_once_with("postgresql://test")
        start_run.assert_awaited_once_with(conn, workspace_key=None, trigger_context={})
        run_phase1.assert_awaited_once_with(conn, rules)
        run_s3_phase1.assert_awaited_once_with(conn, rules.s3)
        save_phase1.assert_awaited_once_with(conn, 77, ["ec2-result"], ["s3-result"])
        run_phase2.assert_awaited_once_with(conn, ["ec2-result"], rules.phase2)
        save_phase2.assert_awaited_once_with(conn, 77, ["phase2-result"])
        self.assertEqual(
            update_status.await_args_list,
            [
                call(conn, 77, "running_phase1"),
                call(conn, 77, "running_phase2"),
                call(conn, 77, "waiting_phase3"),
            ],
        )
        publish_event.assert_awaited_once_with(
            redis_client,
            OPTIMIZATION_STREAM,
            EVENT_DETERMINISTIC_COMPLETE,
            {"run_id": 77, "status": "phase2_completed"},
        )
        self.assertTrue(conn.closed)
        self.assertTrue(redis_client.closed)

    async def test_wait_mode_forwards_safe_trigger_metadata_to_completion_event(self) -> None:
        conn = FakeConnection()
        redis_client = FakeRedis()
        rules = SimpleNamespace(s3="s3-rules", phase2="phase2-rules")
        trigger_payload = {
            "event": EVENT_INGESTION_COMPLETE,
            "workspace_id": "workspace-7",
            "account_id": "account-9",
            "terraform_repo_url": "https://example.test/infrastructure.git",
            "terraform_ref": "production",
        }
        wait_for_event = AsyncMock(return_value=trigger_payload)
        publish_event = AsyncMock(return_value="10-0")

        with (
            patch.dict(
                os.environ,
                {
                    "DATABASE_URL": "postgresql://test",
                    "AGENT1_SKIP_WAIT": "false",
                },
                clear=True,
            ),
            patch.object(agent1_main, "load_rules", Mock(return_value=rules)),
            patch.object(agent1_main.aioredis, "from_url", return_value=redis_client),
            patch.object(agent1_main, "wait_for_event", wait_for_event),
            patch.object(agent1_main, "connect_database", AsyncMock(return_value=conn)),
            patch.object(agent1_main, "start_optimization_run", AsyncMock(return_value=88)) as start_run,
            patch.object(agent1_main, "run_phase1", AsyncMock(return_value=[])),
            patch.object(agent1_main, "run_s3_phase1", AsyncMock(return_value=[])),
            patch.object(agent1_main, "save_phase1_outputs", AsyncMock()),
            patch.object(agent1_main, "run_phase2", AsyncMock(return_value=[])),
            patch.object(agent1_main, "save_phase2_outputs", AsyncMock()),
            patch.object(agent1_main, "update_optimization_run_status", AsyncMock()),
            patch.object(agent1_main, "publish_event", publish_event),
        ):
            await agent1_main.main()

        wait_for_event.assert_awaited_once_with(
            redis_client,
            INGESTION_STREAM,
            EVENT_INGESTION_COMPLETE,
        )
        start_run.assert_awaited_once_with(
            conn,
            workspace_key="workspace-7",
            trigger_context=trigger_payload,
        )
        published_payload = publish_event.await_args.args[3]
        self.assertEqual(published_payload["run_id"], 88)
        self.assertEqual(published_payload["status"], "phase2_completed")
        self.assertEqual(published_payload["workspace_id"], "workspace-7")
        self.assertEqual(published_payload["account_id"], "account-9")
        self.assertEqual(
            published_payload["terraform_repo_url"],
            "https://example.test/infrastructure.git",
        )
        self.assertEqual(published_payload["terraform_ref"], "production")
        self.assertTrue(conn.closed)
        self.assertTrue(redis_client.closed)

    async def test_failure_sets_safe_failed_status_after_run_exists(self) -> None:
        conn = FakeConnection()
        redis_client = FakeRedis()
        rules = SimpleNamespace(s3="s3-rules", phase2="phase2-rules")
        update_status = AsyncMock()

        with (
            patch.dict(
                os.environ,
                {"DATABASE_URL": "postgresql://test", "AGENT1_SKIP_WAIT": "true"},
                clear=True,
            ),
            patch.object(agent1_main, "load_rules", Mock(return_value=rules)),
            patch.object(agent1_main.aioredis, "from_url", return_value=redis_client),
            patch.object(agent1_main, "connect_database", AsyncMock(return_value=conn)),
            patch.object(agent1_main, "start_optimization_run", AsyncMock(return_value=99)),
            patch.object(agent1_main, "update_optimization_run_status", update_status),
            patch.object(agent1_main, "run_phase1", AsyncMock(side_effect=RuntimeError("secret details"))),
        ):
            with self.assertRaises(RuntimeError):
                await agent1_main.main()

        self.assertEqual(
            update_status.await_args_list,
            [
                call(conn, 99, "running_phase1"),
                call(conn, 99, "failed", error_message="Deterministic worker failed"),
            ],
        )
        self.assertTrue(conn.closed)
        self.assertTrue(redis_client.closed)

    def test_agent1_has_no_phase3_or_benchmark_import(self) -> None:
        source = Path(agent1_main.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)

        self.assertFalse(any(name == "phase3" or name.startswith("phase3.") for name in imports))
        self.assertFalse(
            any(name == "llm_benchmarking" or name.startswith("llm_benchmarking.") for name in imports)
        )


if __name__ == "__main__":
    unittest.main()
