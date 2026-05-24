import importlib
import sys
import unittest
from pathlib import Path

from phase1.models import Phase1Result, WasteAction, WasteType
from phase1.s3_models import S3Action, S3FindingResult, S3WasteType
from phase2.models import Phase2Result
from phase3.converter import build_ec2_scenario, build_s3_scenario


class TestPhase3Converter(unittest.TestCase):
    def test_build_ec2_scenario_basic(self) -> None:
        p1 = Phase1Result(
            resource_id=1,
            resource_name="i-test-1",
            role="steady",
            action=WasteAction.STOP,
            waste_type=WasteType.IDLE,
            detection_window_days=7,
            p95_cpu=1.2,
            p99_cpu=2.3,
            max_cpu=3.4,
            p95_ram=12.5,
            cv=0.11,
            current_instance_type="t3.medium",
            recommended_type="t3.small",
            current_cost_per_hour=0.0416,
            waste_per_month=25.0,
            detection_reason="idle instance",
        )

        p2 = Phase2Result(
            resource_id=1,
            instance_name="i-test-1",
            role="steady",
            waste_type=WasteType.IDLE,
            phase1_action=WasteAction.STOP,
            action=WasteAction.STOP,
            detection_reason="idle instance",
            blast_radius=1,
            relationship_count=0,
        )

        scenario = build_ec2_scenario([p1], [p2])
        self.assertIn("flagged_resources", scenario)
        self.assertEqual(len(scenario["flagged_resources"]), 1)
        self.assertEqual(scenario["flagged_resources"][0]["agent2_decision"]["action"], "STOP")
        dumped = p2.model_dump()
        self.assertIn("instance_name", dumped)
        self.assertIn("blast_radius", dumped)
        self.assertNotIn("resource_name", dumped)
        self.assertNotIn("blast_radius_score", dumped)

    def test_skip_maps_to_keep(self) -> None:
        p1 = Phase1Result(
            resource_id=2,
            resource_name="i-test-2",
            role="steady",
            action=WasteAction.STOP,
            waste_type=WasteType.IDLE,
            detection_reason="idle instance",
        )
        p2 = Phase2Result(
            resource_id=2,
            instance_name="i-test-2",
            role="steady",
            waste_type=WasteType.IDLE,
            phase1_action=WasteAction.STOP,
            action=WasteAction.SKIP,
            detection_reason="idle instance",
            phase2_action_changed=True,
            phase2_action_reason="guardrail: high blast radius",
            block_reason="graph suggests critical dependency",
            blast_radius=99,
            relationship_count=20,
        )

        scenario = build_ec2_scenario([p1], [p2])
        dec = scenario["flagged_resources"][0]["agent2_decision"]
        self.assertEqual(dec["action"], "KEEP")
        self.assertIn("block_reason", dec)

    def test_build_s3_scenario_multi(self) -> None:
        r1 = S3FindingResult(
            bucket_name="b1",
            grouping_key="ALL",
            action=S3Action.RECOMMEND_LIFECYCLE,
            waste_type=S3WasteType.STORAGE_MISMATCH,
            pct_older_90_days=80.0,
            estimated_monthly_savings=12.34,
            detection_reason="cold data",
        )
        r2 = S3FindingResult(
            bucket_name="b2",
            grouping_key="ALL",
            action=S3Action.REVIEW,
            waste_type=S3WasteType.MISSING_LIFECYCLE,
            detection_reason="no lifecycle",
        )

        scenario = build_s3_scenario([r1, r2])
        self.assertIn("findings", scenario)
        self.assertEqual(len(scenario["findings"]), 2)

    def test_prompt_builder_accepts_converted_scenario(self) -> None:
        repo_path = Path(__file__).resolve().parents[1] / "llm_benchmarking" / "IaC-Evaluation-Pipeline"
        if not repo_path.exists():
            self.skipTest("IaC-Evaluation-Pipeline repo not present in workspace")

        repo_str = str(repo_path)
        if repo_str not in sys.path:
            sys.path.insert(0, repo_str)

        prompt_builder = importlib.import_module("prompts.prompt_builder")

        p1 = Phase1Result(
            resource_id=3,
            resource_name="i-test-3",
            role="steady",
            action=WasteAction.DOWNSIZE,
            waste_type=WasteType.OVERSIZED,
            detection_reason="oversized",
            p95_cpu=2.0,
            p95_ram=10.0,
            current_instance_type="m5.large",
            recommended_type="t3.medium",
            current_cost_per_hour=0.10,
            waste_per_month=50.0,
        )
        p2 = Phase2Result(
            resource_id=3,
            instance_name="i-test-3",
            role="steady",
            waste_type=WasteType.OVERSIZED,
            phase1_action=WasteAction.DOWNSIZE,
            action=WasteAction.DOWNSIZE,
            detection_reason="oversized",
        )

        scenario = build_ec2_scenario([p1], [p2])
        system_prompt, user_prompt = prompt_builder.build_prompt(scenario)
        self.assertTrue(system_prompt)
        self.assertTrue(user_prompt)


if __name__ == "__main__":
    unittest.main()
