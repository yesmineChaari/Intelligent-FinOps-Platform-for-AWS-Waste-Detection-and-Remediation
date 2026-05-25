"""Persistence write tests for optimization runs and phase output storage.

The suite uses a fake async connection to verify run creation, explicit status
updates and the legacy missing-``error_message`` fallback, compatible final
completion updates, Phase 1 EC2/S3 trace writes, Phase 2 guardrail writes, and
Phase 3 EC2/S3 output persistence for both object and database-loaded dict
inputs.
"""

import unittest

import asyncpg

from persistence.phase_outputs import (
    complete_optimization_run,
    save_phase1_outputs,
    save_phase2_outputs,
    save_phase3_outputs,
    start_optimization_run,
    update_optimization_run_status,
)
from phase1.models import Phase1Result, WasteAction, WasteType
from phase1.s3_models import S3Action, S3FindingResult, S3WasteType
from phase2.models import Phase2Result


class FakeConn:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []
        self.executemany_calls: list[tuple[str, list[tuple]]] = []

    async def execute(self, query: str, *args):
        self.executed.append(query)
        self.execute_calls.append((query, args))
        return None

    async def executemany(self, query: str, rows):
        self.executemany_calls.append((query, list(rows)))
        return None

    async def fetch(self, query: str, *args):
        if "FROM s3_instances" in query:
            return [{"name": "bucket-a", "resource_id": 20}]
        return []

    async def fetchrow(self, query: str, *args):
        if "RETURNING id" in query:
            return {"id": 123}
        return None


class MissingErrorMessageConn(FakeConn):
    async def execute(self, query: str, *args):
        self.executed.append(query)
        self.execute_calls.append((query, args))
        if "error_message = $3" in query:
            raise asyncpg.UndefinedColumnError("error_message does not exist")
        return None


def _queries_for_table(conn: FakeConn, table_name: str) -> list[tuple[str, list[tuple]]]:
    return [(query, rows) for query, rows in conn.executemany_calls if table_name in query]


class TestPhaseOutputPersistence(unittest.IsolatedAsyncioTestCase):
    async def test_start_optimization_run_returns_run_id(self) -> None:
        conn = FakeConn()

        run_id = await start_optimization_run(
            conn,
            workspace_key="aws-prod",
            trigger_context={"event": "ingestion_complete"},
            phase3_model_key="qwen3-coder-32b",
        )

        self.assertEqual(run_id, 123)
        self.assertTrue(any("optimization_runs" in query for query in conn.executed))

    async def test_update_optimization_run_status_updates_status_and_error_by_run_id(self) -> None:
        conn = FakeConn()

        await update_optimization_run_status(conn, 123, "failed", "safe worker failure")

        query, args = conn.execute_calls[0]
        self.assertIn("UPDATE optimization_runs", query)
        self.assertIn("status = $2", query)
        self.assertIn("error_message = $3", query)
        self.assertEqual(args, (123, "failed", "safe worker failure"))

    async def test_update_optimization_run_status_falls_back_without_error_message_column(self) -> None:
        conn = MissingErrorMessageConn()

        await update_optimization_run_status(conn, 123, "running_phase1")

        self.assertEqual(len(conn.execute_calls), 2)
        fallback_query, fallback_args = conn.execute_calls[1]
        self.assertIn("UPDATE optimization_runs", fallback_query)
        self.assertIn("status = $2", fallback_query)
        self.assertNotIn("error_message", fallback_query)
        self.assertEqual(fallback_args, (123, "running_phase1"))

    async def test_complete_optimization_run_retains_final_completion_behavior(self) -> None:
        conn = FakeConn()

        await complete_optimization_run(conn, 123, status="completed")

        query, args = conn.execute_calls[0]
        self.assertIn("completed_at = NOW()", query)
        self.assertEqual(args, (123, "completed", None, None))

    async def test_save_phase1_outputs_separates_ec2_and_s3(self) -> None:
        conn = FakeConn()
        ec2 = Phase1Result(
            resource_id=1,
            resource_name="i-test",
            role="steady",
            action=WasteAction.STOP,
            waste_type=WasteType.IDLE,
            p95_cpu=2.0,
            detection_reason="idle",
        )
        s3 = S3FindingResult(
            bucket_name="bucket-a",
            action=S3Action.RECOMMEND_LIFECYCLE,
            waste_type=S3WasteType.MISSING_LIFECYCLE,
            object_count=10,
            detection_reason="missing lifecycle",
        )

        await save_phase1_outputs(conn, 123, [ec2], [s3])

        ec2_calls = _queries_for_table(conn, "phase1_ec2_outputs")
        s3_calls = _queries_for_table(conn, "phase1_s3_outputs")
        self.assertEqual(len(ec2_calls), 1)
        self.assertEqual(len(s3_calls), 1)
        self.assertEqual(ec2_calls[0][1][0][1], 1)
        self.assertEqual(s3_calls[0][1][0][1], 20)

    async def test_save_phase2_outputs_uses_phase2_trace_table(self) -> None:
        conn = FakeConn()
        p2 = Phase2Result(
            resource_id=1,
            instance_name="i-test",
            role="steady",
            waste_type=WasteType.IDLE,
            phase1_action=WasteAction.STOP,
            action=WasteAction.DOWNSIZE,
            phase2_action_changed=True,
            phase2_action_reason="writes_to dependency",
            blast_radius=2,
            relationship_count=1,
        )

        await save_phase2_outputs(conn, 123, [p2])

        calls = _queries_for_table(conn, "phase2_ec2_outputs")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1][0][1], 1)
        self.assertEqual(calls[0][1][0][6], "DOWNSIZE")

    async def test_save_phase3_outputs_uses_waste_and_s3_waste(self) -> None:
        conn = FakeConn()
        p2 = Phase2Result(
            resource_id=1,
            instance_name="i-test",
            role="steady",
            waste_type=WasteType.IDLE,
            phase1_action=WasteAction.STOP,
            action=WasteAction.STOP,
        )
        s3 = S3FindingResult(
            bucket_name="bucket-a",
            action=S3Action.RECOMMEND_LIFECYCLE,
            waste_type=S3WasteType.MISSING_LIFECYCLE,
        )
        phase3_output = {
            "runs": [
                {
                    "scenario_type": "ec2",
                    "scenario": {
                        "flagged_resources": [
                            {
                                "instance_id": "i-test",
                                "instance_name": "i-test",
                                "agent2_decision": {"action": "STOP"},
                            }
                        ]
                    },
                    "llm": {
                        "parsed": {
                            "verdict": "OPTIMAL",
                            "decision_summary": {
                                "action": "STOP",
                                "decided_by": "AGENT_VALIDATED",
                                "rationale": "idle",
                            },
                            "terraform_action": "SCRIPT_HANDLES",
                        }
                    },
                },
                {
                    "scenario_type": "s3",
                    "scenario": {
                        "finding": {
                            "bucket_name": "bucket-a",
                            "grouping_key": "ALL",
                            "finding_type": "GLACIER_TRANSITION",
                        },
                        "agent2_decision": {"action": "GLACIER_TRANSITION"},
                    },
                    "llm": {
                        "parsed": {
                            "verdict": "OPTIMAL",
                            "decision_summary": {
                                "action": "GLACIER_TRANSITION",
                                "decided_by": "AGENT_VALIDATED",
                                "rationale": "old objects",
                            },
                            "terraform_action": "SCRIPT_HANDLES",
                        }
                    },
                },
            ]
        }

        await save_phase3_outputs(conn, 123, phase3_output, phase2_results=[p2], s3_results=[s3])

        ec2_calls = _queries_for_table(conn, "INSERT INTO waste")
        s3_calls = _queries_for_table(conn, "INSERT INTO s3_waste")
        self.assertEqual(len(ec2_calls), 1)
        self.assertEqual(len(s3_calls), 1)
        self.assertEqual(ec2_calls[0][1][0][1], 1)
        self.assertEqual(s3_calls[0][1][0][2], "bucket-a")

    async def test_save_phase3_outputs_accepts_database_loaded_dict_context(self) -> None:
        conn = FakeConn()
        phase2_results = [
            {
                "resource_id": 1,
                "instance_name": "i-test",
                "waste_type": "idle",
            }
        ]
        s3_results = [{"bucket_name": "bucket-a"}]
        phase3_output = {
            "runs": [
                {
                    "scenario_type": "ec2",
                    "scenario": {
                        "flagged_resources": [
                            {
                                "instance_id": "i-test",
                                "instance_name": "i-test",
                                "agent2_decision": {"action": "STOP"},
                            }
                        ]
                    },
                    "llm": {},
                },
                {
                    "scenario_type": "s3",
                    "scenario": {
                        "finding": {
                            "bucket_name": "bucket-a",
                            "grouping_key": "ALL",
                        },
                        "agent2_decision": {"action": "GLACIER_TRANSITION"},
                    },
                    "llm": {},
                },
            ]
        }

        await save_phase3_outputs(
            conn,
            123,
            phase3_output,
            phase2_results=phase2_results,
            s3_results=s3_results,
        )

        ec2_calls = _queries_for_table(conn, "INSERT INTO waste")
        s3_calls = _queries_for_table(conn, "INSERT INTO s3_waste")
        self.assertEqual(ec2_calls[0][1][0][1], 1)
        self.assertEqual(s3_calls[0][1][0][1], 20)
