import unittest
from types import SimpleNamespace

from phase3.converter import build_ec2_scenario, build_s3_scenario


class TestPhase3ConverterDictInputs(unittest.TestCase):
    def test_ec2_phase1_and_phase2_dicts_build_scenario(self) -> None:
        phase1 = {
            "resource_id": 1,
            "resource_name": "i-dict",
            "role": "steady",
            "action": "DOWNSIZE",
            "waste_type": "oversized",
            "detection_reason": "underused",
            "p95_cpu": 4.2,
            "current_instance_type": "m5.large",
            "recommended_type": "m5.medium",
            "current_cost_per_hour": 0.10,
            "recommended_cost_per_hour": 0.05,
            "waste_per_month": 36.5,
        }
        phase2 = {
            "resource_id": 1,
            "instance_name": "i-dict",
            "action": "DOWNSIZE",
            "phase1_action": "DOWNSIZE",
            "blast_radius": 1,
        }

        scenario = build_ec2_scenario([phase1], [phase2])
        resource = scenario["flagged_resources"][0]

        self.assertEqual(resource["instance_name"], "i-dict")
        self.assertEqual(resource["agent2_decision"]["action"], "DOWNSIZE")
        self.assertEqual(resource["agent2_decision"]["p95_cpu"], 4.2)
        self.assertEqual(resource["cost"]["waste_per_month"], 36.5)

    def test_s3_phase1_dict_builds_scenario(self) -> None:
        result = {
            "bucket_name": "archive-bucket",
            "grouping_key": "ALL",
            "action": "RECOMMEND_LIFECYCLE",
            "waste_type": "storage_mismatch",
            "pct_older_90_days": 82.0,
            "estimated_monthly_savings": 10.5,
            "detection_reason": "cold objects",
        }

        scenario = build_s3_scenario([result])

        self.assertEqual(scenario["finding"]["bucket_name"], "archive-bucket")
        self.assertEqual(scenario["finding"]["finding_type"], "GLACIER_TRANSITION")
        self.assertEqual(scenario["agent2_decision"]["action"], "GLACIER_TRANSITION")

    def test_object_and_dict_inputs_produce_the_same_scenarios(self) -> None:
        phase1 = {
            "resource_id": 2,
            "resource_name": "i-object",
            "action": "STOP",
            "waste_type": "idle",
        }
        phase2 = {
            "resource_id": 2,
            "instance_name": "i-object",
            "action": "STOP",
        }
        s3_result = {
            "bucket_name": "object-bucket",
            "action": "REVIEW",
            "waste_type": "missing_lifecycle",
        }

        dict_ec2 = build_ec2_scenario([phase1], [phase2])
        object_ec2 = build_ec2_scenario(
            [SimpleNamespace(**phase1)],
            [SimpleNamespace(**phase2)],
        )
        dict_s3 = build_s3_scenario([s3_result])
        object_s3 = build_s3_scenario([SimpleNamespace(**s3_result)])

        self.assertEqual(dict_ec2, object_ec2)
        self.assertEqual(dict_s3, object_s3)

    def test_missing_optional_fields_do_not_crash_dict_conversion(self) -> None:
        ec2 = build_ec2_scenario(
            [{"resource_id": 3, "action": "STOP"}],
            [{"resource_id": 3, "action": "STOP"}],
        )
        s3 = build_s3_scenario([{"bucket_name": "minimal-bucket"}])

        resource = ec2["flagged_resources"][0]
        self.assertEqual(resource["instance_name"], "3")
        self.assertIsNone(resource["instance_type"])
        self.assertEqual(s3["finding"]["bucket_name"], "minimal-bucket")
        self.assertEqual(s3["finding"]["finding_type"], "S3_OPTIMIZATION")


if __name__ == "__main__":
    unittest.main()
