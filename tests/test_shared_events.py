"""Unit tests for shared Redis Stream publication and waiting helpers.

Using fake Redis readers and publishers, these tests verify string conversion
and omission of absent payload values without mutation, automatic event field
insertion, ignoring unrelated events while reading, stream cursor advancement,
and decoding of both byte and string Redis field representations.
"""

import unittest

from shared.events import (
    EVENT_DETERMINISTIC_COMPLETE,
    EVENT_INGESTION_COMPLETE,
    INGESTION_STREAM,
    OPTIMIZATION_STREAM,
    publish_event,
    wait_for_event,
)


class FakePublisher:
    def __init__(self) -> None:
        self.xadd_calls: list[tuple[str, dict[str, str]]] = []

    async def xadd(self, stream_name: str, fields: dict[str, str]) -> bytes:
        self.xadd_calls.append((stream_name, fields))
        return b"7-0"


class FakeReader:
    def __init__(self, responses: list[list[tuple[object, list[tuple[object, dict]]]]]) -> None:
        self.responses = list(responses)
        self.xread_calls: list[tuple[dict[str, object], int, int]] = []

    async def xread(self, streams: dict[str, object], *, block: int, count: int):
        self.xread_calls.append((streams, block, count))
        if not self.responses:
            raise AssertionError("wait_for_event requested an unexpected additional read")
        return self.responses.pop(0)


class TestSharedEvents(unittest.IsolatedAsyncioTestCase):
    async def test_publish_event_serializes_payload_and_preserves_input(self) -> None:
        redis_client = FakePublisher()
        payload: dict[str, object] = {
            "run_id": 42,
            "workspace_key": "prod",
            "terraform_ref": None,
            "event": "caller-value",
        }
        original_payload = dict(payload)

        entry_id = await publish_event(
            redis_client,
            OPTIMIZATION_STREAM,
            EVENT_DETERMINISTIC_COMPLETE,
            payload,
        )

        self.assertEqual(entry_id, "7-0")
        self.assertEqual(payload, original_payload)
        self.assertEqual(
            redis_client.xadd_calls,
            [
                (
                    OPTIMIZATION_STREAM,
                    {
                        "run_id": "42",
                        "workspace_key": "prod",
                        "event": EVENT_DETERMINISTIC_COMPLETE,
                    },
                )
            ],
        )

    async def test_wait_for_event_ignores_other_bytes_event_and_decodes_target(self) -> None:
        redis_client = FakeReader(
            [
                [
                    (
                        b"ingestion_stream",
                        [(b"1-0", {b"event": b"unrelated", b"ignored": b"value"})],
                    )
                ],
                [
                    (
                        b"ingestion_stream",
                        [
                            (
                                b"2-0",
                                {
                                    b"event": b"ingestion_complete",
                                    b"workspace_key": b"aws-prod",
                                },
                            )
                        ],
                    )
                ],
            ]
        )

        payload = await wait_for_event(
            redis_client,
            INGESTION_STREAM,
            EVENT_INGESTION_COMPLETE,
            block_ms=250,
            count=2,
        )

        self.assertEqual(
            payload,
            {"event": EVENT_INGESTION_COMPLETE, "workspace_key": "aws-prod"},
        )
        self.assertEqual(
            redis_client.xread_calls,
            [
                ({INGESTION_STREAM: "$"}, 250, 2),
                ({INGESTION_STREAM: b"1-0"}, 250, 2),
            ],
        )

    async def test_wait_for_event_accepts_string_fields(self) -> None:
        redis_client = FakeReader(
            [
                [
                    (
                        INGESTION_STREAM,
                        [
                            (
                                "3-0",
                                {
                                    "event": EVENT_INGESTION_COMPLETE,
                                    "terraform_ref": "main",
                                },
                            )
                        ],
                    )
                ]
            ]
        )

        payload = await wait_for_event(
            redis_client,
            INGESTION_STREAM,
            EVENT_INGESTION_COMPLETE,
        )

        self.assertEqual(
            payload,
            {"event": EVENT_INGESTION_COMPLETE, "terraform_ref": "main"},
        )


if __name__ == "__main__":
    unittest.main()
