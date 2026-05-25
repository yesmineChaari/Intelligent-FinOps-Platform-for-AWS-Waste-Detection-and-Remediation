import os
import unittest
from unittest.mock import patch

from agent1.main import _deterministic_event_payload
from agent2.main import _SAFE_FAILURE_MESSAGE, _parse_run_id
from shared.events import (
    EVENT_DETERMINISTIC_COMPLETE,
    EVENT_PHASE3_COMPLETE,
    EVENT_PHASE3_FAILED,
    OPTIMIZATION_STREAM,
    build_deterministic_complete_payload,
    decode_stream_fields,
    publish_event,
)


class FakeRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, str]]] = []

    async def xadd(self, stream_name: str, fields: dict[str, str]) -> bytes:
        self.published.append((stream_name, fields))
        return b"12-0"


class TestAgentEventContracts(unittest.IsolatedAsyncioTestCase):
    def test_deterministic_payload_builder_stringifies_and_omits_none(self) -> None:
        payload = build_deterministic_complete_payload(
            41,
            workspace_key=None,
            terraform_repo_url="https://example.test/terraform.git",
            terraform_ref="main",
            terraform_subdir=None,
        )

        self.assertEqual(
            payload,
            {
                "run_id": "41",
                "terraform_repo_url": "https://example.test/terraform.git",
                "terraform_ref": "main",
            },
        )
        self.assertTrue(all(isinstance(value, str) for value in payload.values()))

    async def test_agent1_deterministic_event_contract_adds_event_and_serializes_values(self) -> None:
        redis_client = FakeRedis()
        with patch.dict(os.environ, {}, clear=True):
            payload = _deterministic_event_payload(
                {"workspace_key": "workspace-a", "terraform_subdir": None},
                57,
            )

        await publish_event(
            redis_client,
            OPTIMIZATION_STREAM,
            EVENT_DETERMINISTIC_COMPLETE,
            payload,
        )

        self.assertEqual(
            redis_client.published,
            [
                (
                    OPTIMIZATION_STREAM,
                    {
                        "run_id": "57",
                        "status": "phase2_completed",
                        "workspace_key": "workspace-a",
                        "event": EVENT_DETERMINISTIC_COMPLETE,
                    },
                )
            ],
        )

    def test_ingestion_metadata_decoding_supports_terraform_context(self) -> None:
        decoded = decode_stream_fields(
            {
                b"workspace_key": b"workspace-a",
                b"terraform_repo_url": b"https://example.test/terraform.git",
                b"terraform_ref": b"release",
                b"terraform_subdir": b"environments/prod",
            }
        )

        self.assertEqual(
            decoded,
            {
                "workspace_key": "workspace-a",
                "terraform_repo_url": "https://example.test/terraform.git",
                "terraform_ref": "release",
                "terraform_subdir": "environments/prod",
            },
        )

    async def test_phase3_complete_event_contains_run_id_and_status(self) -> None:
        redis_client = FakeRedis()

        entry_id = await publish_event(
            redis_client,
            OPTIMIZATION_STREAM,
            EVENT_PHASE3_COMPLETE,
            {"run_id": 82, "status": "completed"},
        )

        self.assertEqual(entry_id, "12-0")
        self.assertEqual(
            redis_client.published[0][1],
            {"run_id": "82", "status": "completed", "event": EVENT_PHASE3_COMPLETE},
        )

    async def test_phase3_failed_event_uses_safe_error_field(self) -> None:
        redis_client = FakeRedis()

        await publish_event(
            redis_client,
            OPTIMIZATION_STREAM,
            EVENT_PHASE3_FAILED,
            {
                "run_id": 83,
                "status": "phase3_failed",
                "error_message": _SAFE_FAILURE_MESSAGE,
            },
        )

        self.assertEqual(
            redis_client.published[0][1],
            {
                "run_id": "83",
                "status": "phase3_failed",
                "error_message": "Phase 3 worker failed",
                "event": EVENT_PHASE3_FAILED,
            },
        )

    def test_agent2_manual_run_id_parser_accepts_integer_text_and_rejects_invalid_value(self) -> None:
        self.assertEqual(_parse_run_id(" 123 "), 123)
        with self.assertRaisesRegex(ValueError, "integer"):
            _parse_run_id("not-a-run-id")


if __name__ == "__main__":
    unittest.main()
