import ast
import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, call, patch

import agent2.main as agent2_main
from shared.events import (
    EVENT_DETERMINISTIC_COMPLETE,
    EVENT_PHASE3_COMPLETE,
    EVENT_PHASE3_FAILED,
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


class TestAgent2Entrypoint(unittest.IsolatedAsyncioTestCase):
    async def test_manual_run_id_skips_wait_and_runs_phase3(self) -> None:
        conn = FakeConnection()
        redis_client = FakeRedis()
        phase1_results = [{"resource_id": 1}]
        s3_results = [{"bucket_name": "bucket-a"}]
        phase2_results = [{"resource_id": 1}]
        phase3_output = {"runs": []}
        execution_order: list[str] = []
        wait_for_event = AsyncMock()
        run_phase3 = Mock(side_effect=lambda *args, **kwargs: execution_order.append("phase3") or phase3_output)
        save_phase3 = AsyncMock()
        update_status = AsyncMock(side_effect=lambda *args, **kwargs: execution_order.append("running_phase3"))
        complete_run = AsyncMock()
        publish_event = AsyncMock(return_value="10-0")

        with (
            patch.dict(
                os.environ,
                {
                    "NEON_DATABASE_URL": "postgresql://manual",
                    "REDIS_URL": "redis://unit-test:6379",
                    "AGENT2_RUN_ID": "55",
                    "PHASE3_MODEL": "model-a",
                    "PHASE3_TERRAFORM_REPO_URL": "https://example.test/tf.git",
                },
                clear=True,
            ),
            patch.object(agent2_main.aioredis, "from_url", return_value=redis_client) as from_url,
            patch.object(agent2_main, "wait_for_event", wait_for_event),
            patch.object(agent2_main, "connect_database", AsyncMock(return_value=conn)) as connect_database,
            patch.object(agent2_main, "load_phase1_ec2_outputs", AsyncMock(return_value=phase1_results)) as load_ec2,
            patch.object(agent2_main, "load_phase1_s3_outputs", AsyncMock(return_value=s3_results)) as load_s3,
            patch.object(agent2_main, "load_phase2_ec2_outputs", AsyncMock(return_value=phase2_results)) as load_p2,
            patch.object(agent2_main, "run_phase3_llm", run_phase3),
            patch.object(agent2_main, "save_phase3_outputs", save_phase3),
            patch.object(agent2_main, "update_optimization_run_status", update_status),
            patch.object(agent2_main, "complete_optimization_run", complete_run),
            patch.object(agent2_main, "publish_event", publish_event),
        ):
            run_id = await agent2_main.main()

        self.assertEqual(run_id, 55)
        from_url.assert_called_once_with("redis://unit-test:6379", decode_responses=False)
        wait_for_event.assert_not_awaited()
        connect_database.assert_awaited_once_with("postgresql://manual")
        load_ec2.assert_awaited_once_with(conn, 55)
        load_s3.assert_awaited_once_with(conn, 55)
        load_p2.assert_awaited_once_with(conn, 55)
        run_phase3.assert_called_once_with(
            phase1_results,
            phase2_results,
            s3_results,
            model_key="model-a",
            terraform_source={
                "repo_url": "https://example.test/tf.git",
                "ref": None,
                "subdir": None,
            },
        )
        save_phase3.assert_awaited_once_with(
            conn,
            55,
            phase3_output,
            phase2_results=phase2_results,
            s3_results=s3_results,
        )
        update_status.assert_awaited_once_with(conn, 55, "running_phase3")
        self.assertLess(execution_order.index("running_phase3"), execution_order.index("phase3"))
        complete_run.assert_awaited_once_with(conn, 55, status="completed")
        publish_event.assert_awaited_once_with(
            redis_client,
            OPTIMIZATION_STREAM,
            EVENT_PHASE3_COMPLETE,
            {"run_id": 55, "status": "completed"},
        )
        self.assertTrue(conn.closed)
        self.assertTrue(redis_client.closed)

    async def test_event_mode_parses_run_id_and_prefers_event_terraform_metadata(self) -> None:
        conn = FakeConnection()
        redis_client = FakeRedis()
        event_payload = {
            "event": EVENT_DETERMINISTIC_COMPLETE,
            "run_id": "91",
            "terraform_repo_url": "https://example.test/event.git",
            "terraform_ref": "release",
        }
        wait_for_event = AsyncMock(return_value=event_payload)
        run_phase3 = Mock(return_value={"runs": []})

        with (
            patch.dict(
                os.environ,
                {
                    "DATABASE_URL": "postgresql://event",
                    "PHASE3_TERRAFORM_REPO_URL": "https://example.test/env.git",
                    "PHASE3_TERRAFORM_SUBDIR": "env/path",
                },
                clear=True,
            ),
            patch.object(agent2_main.aioredis, "from_url", return_value=redis_client),
            patch.object(agent2_main, "wait_for_event", wait_for_event),
            patch.object(agent2_main, "connect_database", AsyncMock(return_value=conn)),
            patch.object(agent2_main, "load_phase1_ec2_outputs", AsyncMock(return_value=[])),
            patch.object(agent2_main, "load_phase1_s3_outputs", AsyncMock(return_value=[])),
            patch.object(agent2_main, "load_phase2_ec2_outputs", AsyncMock(return_value=[])),
            patch.object(agent2_main, "run_phase3_llm", run_phase3),
            patch.object(agent2_main, "save_phase3_outputs", AsyncMock()),
            patch.object(agent2_main, "update_optimization_run_status", AsyncMock()),
            patch.object(agent2_main, "complete_optimization_run", AsyncMock()),
            patch.object(agent2_main, "publish_event", AsyncMock()),
        ):
            run_id = await agent2_main.main()

        self.assertEqual(run_id, 91)
        wait_for_event.assert_awaited_once_with(
            redis_client,
            OPTIMIZATION_STREAM,
            EVENT_DETERMINISTIC_COMPLETE,
        )
        self.assertEqual(
            run_phase3.call_args.kwargs["terraform_source"],
            {
                "repo_url": "https://example.test/event.git",
                "ref": "release",
                "subdir": "env/path",
            },
        )

    async def test_phase3_failure_marks_run_failed_and_publishes_safe_event(self) -> None:
        conn = FakeConnection()
        redis_client = FakeRedis()
        update_status = AsyncMock()
        publish_event = AsyncMock(return_value="failed-0")

        with (
            patch.dict(
                os.environ,
                {"DATABASE_URL": "postgresql://test", "AGENT2_RUN_ID": "99"},
                clear=True,
            ),
            patch.object(agent2_main.aioredis, "from_url", return_value=redis_client),
            patch.object(agent2_main, "connect_database", AsyncMock(return_value=conn)),
            patch.object(agent2_main, "load_phase1_ec2_outputs", AsyncMock(return_value=[])),
            patch.object(agent2_main, "load_phase1_s3_outputs", AsyncMock(return_value=[])),
            patch.object(agent2_main, "load_phase2_ec2_outputs", AsyncMock(return_value=[])),
            patch.object(agent2_main, "run_phase3_llm", Mock(side_effect=RuntimeError("secret details"))),
            patch.object(agent2_main, "save_phase3_outputs", AsyncMock()) as save_phase3,
            patch.object(agent2_main, "update_optimization_run_status", update_status),
            patch.object(agent2_main, "publish_event", publish_event),
        ):
            with self.assertRaises(RuntimeError):
                await agent2_main.main()

        save_phase3.assert_not_awaited()
        self.assertEqual(
            update_status.await_args_list,
            [
                call(conn, 99, "running_phase3"),
                call(conn, 99, "phase3_failed", error_message="Phase 3 worker failed"),
            ],
        )
        publish_event.assert_awaited_once_with(
            redis_client,
            OPTIMIZATION_STREAM,
            EVENT_PHASE3_FAILED,
            {
                "status": "phase3_failed",
                "error_message": "Phase 3 worker failed",
                "run_id": 99,
            },
        )
        self.assertTrue(conn.closed)
        self.assertTrue(redis_client.closed)

    async def test_invalid_manual_run_id_is_rejected_without_database_connection(self) -> None:
        redis_client = FakeRedis()
        connect_database = AsyncMock()
        publish_event = AsyncMock()

        with (
            patch.dict(
                os.environ,
                {"DATABASE_URL": "postgresql://test", "AGENT2_RUN_ID": "not-an-id"},
                clear=True,
            ),
            patch.object(agent2_main.aioredis, "from_url", return_value=redis_client),
            patch.object(agent2_main, "connect_database", connect_database),
            patch.object(agent2_main, "publish_event", publish_event),
        ):
            with self.assertRaisesRegex(ValueError, "integer"):
                await agent2_main.main()

        connect_database.assert_not_awaited()
        publish_event.assert_awaited_once_with(
            redis_client,
            OPTIMIZATION_STREAM,
            EVENT_PHASE3_FAILED,
            {
                "status": "phase3_failed",
                "error_message": "Phase 3 worker failed",
            },
        )
        self.assertTrue(redis_client.closed)

    def test_agent2_has_no_phase1_or_phase2_execution_import(self) -> None:
        source = Path(agent2_main.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)

        forbidden = ("phase1", "phase2")
        self.assertFalse(
            any(name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden for name in imports)
        )


if __name__ == "__main__":
    unittest.main()
