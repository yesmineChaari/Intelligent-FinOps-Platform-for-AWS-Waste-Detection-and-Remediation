import unittest

from shared.persistence import (
    load_phase1_ec2_outputs,
    load_phase1_s3_outputs,
    load_phase2_ec2_outputs,
)


class FakeConn:
    def __init__(self, rows_by_table: dict[str, list[dict]] | None = None) -> None:
        self.rows_by_table = rows_by_table or {}
        self.fetch_calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch(self, query: str, *args: object) -> list[dict]:
        self.fetch_calls.append((query, args))
        for table_name, rows in self.rows_by_table.items():
            if f"FROM {table_name}" in query:
                return rows
        return []


class TestPersistenceReadOutputs(unittest.IsolatedAsyncioTestCase):
    async def test_load_phase1_ec2_outputs_queries_run_in_id_order(self) -> None:
        conn = FakeConn()

        results = await load_phase1_ec2_outputs(conn, 123)

        self.assertEqual(results, [])
        query, args = conn.fetch_calls[0]
        self.assertIn("FROM phase1_ec2_outputs", query)
        self.assertIn("WHERE run_id = $1", query)
        self.assertIn("ORDER BY id", query)
        self.assertEqual(args, (123,))

    async def test_load_phase1_s3_outputs_queries_run_in_id_order(self) -> None:
        conn = FakeConn()

        results = await load_phase1_s3_outputs(conn, 456)

        self.assertEqual(results, [])
        query, args = conn.fetch_calls[0]
        self.assertIn("FROM phase1_s3_outputs", query)
        self.assertIn("WHERE run_id = $1", query)
        self.assertIn("ORDER BY id", query)
        self.assertEqual(args, (456,))

    async def test_load_phase2_ec2_outputs_queries_run_in_id_order(self) -> None:
        conn = FakeConn()

        results = await load_phase2_ec2_outputs(conn, 789)

        self.assertEqual(results, [])
        query, args = conn.fetch_calls[0]
        self.assertIn("FROM phase2_ec2_outputs", query)
        self.assertIn("WHERE run_id = $1", query)
        self.assertIn("ORDER BY id", query)
        self.assertEqual(args, (789,))

    async def test_raw_output_is_merged_with_columns_taking_precedence(self) -> None:
        conn = FakeConn(
            {
                "phase1_ec2_outputs": [
                    {
                        "id": 1,
                        "run_id": 123,
                        "action": "STOP",
                        "raw_output": {
                            "action": "KEEP",
                            "detection_reason": "raw reason",
                        },
                    }
                ]
            }
        )

        results = await load_phase1_ec2_outputs(conn, 123)

        self.assertEqual(results[0]["action"], "STOP")
        self.assertEqual(results[0]["detection_reason"], "raw reason")
        self.assertEqual(results[0]["run_id"], 123)

    async def test_all_loaders_return_empty_list_when_no_rows_exist(self) -> None:
        conn = FakeConn()

        results = await load_phase1_ec2_outputs(conn, 1)
        s3_results = await load_phase1_s3_outputs(conn, 1)
        phase2_results = await load_phase2_ec2_outputs(conn, 1)

        self.assertEqual(results, [])
        self.assertEqual(s3_results, [])
        self.assertEqual(phase2_results, [])


if __name__ == "__main__":
    unittest.main()
