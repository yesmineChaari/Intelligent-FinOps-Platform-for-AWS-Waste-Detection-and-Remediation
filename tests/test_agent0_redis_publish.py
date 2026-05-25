"""Integration tests for Agent0's Redis completion handoff.

These tests execute the Agent0 pipeline entrypoint with stubbed application
dependencies and a fake Redis client. They verify successful publication on
``ingestion_stream``, the safe metadata whitelist, compatibility with Agent1,
safe skipping when ``REDIS_URL`` is absent, non-fatal Redis failures, and no
completion event when initial discovery fails.
"""

import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agent1.main import _deterministic_event_payload
from shared.events import EVENT_INGESTION_COMPLETE, INGESTION_STREAM


ROOT = Path(__file__).resolve().parents[1]


class FakeFastAPI:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    def include_router(self, *args, **kwargs) -> None:
        return None

    def get(self, _path: str):
        return lambda function: function


class FakeScheduler:
    def add_job(self, *args, **kwargs) -> None:
        return None

    def start(self) -> None:
        return None

    def shutdown(self, **kwargs) -> None:
        return None


class FakeRedis:
    def __init__(self, *, fail_publish: bool = False) -> None:
        self.fail_publish = fail_publish
        self.xadd_calls: list[tuple[str, dict[str, str]]] = []
        self.closed = False

    def xadd(self, stream_name: str, fields: dict[str, str]) -> str:
        if self.fail_publish:
            raise RuntimeError("redis unavailable")
        self.xadd_calls.append((stream_name, fields))
        return "1-0"

    def close(self) -> None:
        self.closed = True


def _load_agent0_main():
    fastapi = types.ModuleType("fastapi")
    fastapi.FastAPI = FakeFastAPI

    apscheduler = types.ModuleType("apscheduler")
    schedulers = types.ModuleType("apscheduler.schedulers")
    background = types.ModuleType("apscheduler.schedulers.background")
    background.BackgroundScheduler = FakeScheduler

    api = types.ModuleType("api")
    for name in ("ec2", "s3", "dynamodb", "relationships"):
        setattr(api, name, types.SimpleNamespace(router=object()))

    services = types.ModuleType("services")
    discovery = types.ModuleType("services.discovery")
    discovery.run_discovery = Mock()
    cloudwatch = types.ModuleType("services.cloudwatch_injector")
    cloudwatch.inject_all_metrics = Mock()
    ec2_metrics = types.ModuleType("services.ec2_metrics")
    ec2_metrics.run_ec2_metrics_collection = Mock()
    s3_metrics = types.ModuleType("services.s3_metrics")
    s3_metrics.run_s3_metrics_collection = Mock()
    dynamodb_metrics = types.ModuleType("services.dynamodb_metrics")
    dynamodb_metrics.run_dynamodb_metrics_collection = Mock()
    s3_sampler = types.ModuleType("services.s3_sampler")
    s3_sampler.run_s3_object_sampler = Mock()

    stubs = {
        "fastapi": fastapi,
        "apscheduler": apscheduler,
        "apscheduler.schedulers": schedulers,
        "apscheduler.schedulers.background": background,
        "api": api,
        "services": services,
        "services.discovery": discovery,
        "services.cloudwatch_injector": cloudwatch,
        "services.ec2_metrics": ec2_metrics,
        "services.s3_metrics": s3_metrics,
        "services.dynamodb_metrics": dynamodb_metrics,
        "services.s3_sampler": s3_sampler,
    }
    source_path = ROOT / "agent0" / "app" / "main.py"
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location("agent0_main_redis_test", source_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


class TestAgent0RedisPublish(unittest.TestCase):
    def test_successful_ingestion_publishes_safe_ingestion_complete_metadata(self) -> None:
        agent0_main = _load_agent0_main()
        redis_client = FakeRedis()
        environment = {
            "REDIS_URL": "redis://unit-test:6379",
            "WORKSPACE_KEY": "workspace-a",
            "ACCOUNT_ID": "account-7",
            "PHASE3_TERRAFORM_REPO_URL": "https://example.test/infra.git",
            "PHASE3_TERRAFORM_REF": "production",
            "PHASE3_TERRAFORM_SUBDIR": "env/prod",
            "RAW_INVENTORY": "must-not-be-published",
            "DATABASE_URL": "postgresql://must-not-be-published",
        }

        with (
            patch.dict(os.environ, environment, clear=True),
            patch.object(agent0_main.redis.Redis, "from_url", return_value=redis_client) as from_url,
        ):
            agent0_main.run_full_pipeline()

        from_url.assert_called_once_with("redis://unit-test:6379", decode_responses=True)
        self.assertEqual(agent0_main.INGESTION_STREAM, INGESTION_STREAM)
        self.assertEqual(agent0_main.EVENT_INGESTION_COMPLETE, EVENT_INGESTION_COMPLETE)
        self.assertEqual(
            redis_client.xadd_calls,
            [
                (
                    INGESTION_STREAM,
                    {
                        "event": EVENT_INGESTION_COMPLETE,
                        "status": "completed",
                        "workspace_key": "workspace-a",
                        "account_id": "account-7",
                        "terraform_repo_url": "https://example.test/infra.git",
                        "terraform_ref": "production",
                        "terraform_subdir": "env/prod",
                    },
                )
            ],
        )
        payload = redis_client.xadd_calls[0][1]
        self.assertNotIn("RAW_INVENTORY", payload)
        self.assertNotIn("DATABASE_URL", payload)
        self.assertTrue(redis_client.closed)

        with patch.dict(os.environ, {}, clear=True):
            forwarded = _deterministic_event_payload(payload, 71)
        self.assertEqual(forwarded["workspace_key"], "workspace-a")
        self.assertEqual(forwarded["terraform_ref"], "production")

    def test_missing_redis_url_skips_publication_without_failing_ingestion(self) -> None:
        agent0_main = _load_agent0_main()

        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(agent0_main.redis.Redis, "from_url") as from_url,
            self.assertLogs(agent0_main.logger.name, level="WARNING") as logs,
        ):
            agent0_main.run_full_pipeline()

        from_url.assert_not_called()
        self.assertTrue(any("skipping ingestion_complete publication" in message for message in logs.output))

    def test_redis_failure_is_non_fatal_after_successful_ingestion(self) -> None:
        agent0_main = _load_agent0_main()
        redis_client = FakeRedis(fail_publish=True)

        with (
            patch.dict(os.environ, {"REDIS_URL": "redis://unit-test:6379"}, clear=True),
            patch.object(agent0_main.redis.Redis, "from_url", return_value=redis_client),
            self.assertLogs(agent0_main.logger.name, level="WARNING") as logs,
        ):
            agent0_main.run_full_pipeline()

        self.assertTrue(any("Redis event publication failed" in message for message in logs.output))
        self.assertTrue(redis_client.closed)

    def test_failed_discovery_does_not_publish_completion_event(self) -> None:
        agent0_main = _load_agent0_main()
        agent0_main.run_discovery.side_effect = RuntimeError("discovery failed")

        with (
            patch.dict(os.environ, {"REDIS_URL": "redis://unit-test:6379"}, clear=True),
            patch.object(agent0_main.redis.Redis, "from_url") as from_url,
        ):
            agent0_main.run_full_pipeline()

        from_url.assert_not_called()


if __name__ == "__main__":
    unittest.main()
