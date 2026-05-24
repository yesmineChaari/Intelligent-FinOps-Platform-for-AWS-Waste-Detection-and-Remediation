import unittest

from persistence.phase_outputs import (
    save_phase1_outputs,
    save_phase2_outputs,
    save_phase3_outputs,
    start_optimization_run,
)
from phase1.models import Phase1Result, WasteAction, WasteType
from phase1.s3_models import S3Action, S3FindingResult, S3WasteType
from phase2.models import Phase2Result


class FakeConn:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.executemany_calls: list[tuple[str, list[tuple]]] = []

    async def execute(self, query: str, *args):
        self.executed.append(query)
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
