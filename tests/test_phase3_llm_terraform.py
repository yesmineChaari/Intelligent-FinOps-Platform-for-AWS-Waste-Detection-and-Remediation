"""Tests for Terraform-context integration in Phase 3 LLM execution.

With benchmark imports and Terraform resolution mocked, these tests verify the
empty-context path, propagation of resolved Terraform bundles into EC2 and S3
scenarios, and graceful warning behavior when Terraform source retrieval
fails while LLM processing continues.
"""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from phase1.models import Phase1Result, WasteAction, WasteType
from phase1.s3_models import S3Action, S3FindingResult, S3WasteType
from phase2.models import Phase2Result
from phase3.github_terraform import TerraformBundle, TerraformSource
from phase3.llm_phase3 import run_phase3_llm


class _FakePromptBuilder:
    @staticmethod
    def build_prompt(scenario):
        return "system", f"user:{scenario.get('scenario_id')}"


class _FakeRunner:
    def run(self, system_prompt, user_prompt):
        return {"parsed": {"verdict": "OPTIMAL"}}


class _DownsizeRunner:
    def run(self, system_prompt, user_prompt):
        return {
            "parsed": {
                "verdict": "OPTIMAL",
                "decision_summary": {
                    "action": "DOWNSIZE",
                    "decided_by": "AGENT_VALIDATED",
                    "rationale": "Validated downsizing recommendation.",
                },
                "terraform_block": 'module "i_001" {\n  instance_type = "c5.large"\n}',
                "terraform_action": "LLM_GENERATED",
                "modified_files": [
                    {
                        "file_path": "unexpected.tf",
                        "new_content": "resource should be ignored",
                    }
                ],
            }
        }


class _FakeRunners:
    @staticmethod
    def get_runner(model_cfg, api_keys):
        return _FakeRunner()


class _DownsizeRunners:
    @staticmethod
    def get_runner(model_cfg, api_keys):
        return _DownsizeRunner()


def _fake_iac_eval():
    config = SimpleNamespace(MODELS={"unit-test": {"provider": "fake", "model_id": "fake-model"}})
    return config, _FakePromptBuilder, _FakeRunners


def _fake_downsize_iac_eval():
    config = SimpleNamespace(MODELS={"unit-test": {"provider": "fake", "model_id": "fake-model"}})
    return config, _FakePromptBuilder, _DownsizeRunners


def _ec2_inputs():
    phase1 = Phase1Result(
        resource_id=1,
        resource_name="i-test",
        role="steady",
        action=WasteAction.DOWNSIZE,
        waste_type=WasteType.OVERSIZED,
    )
    phase2 = Phase2Result(
        resource_id=1,
        instance_name="i-test",
        role="steady",
        waste_type=WasteType.OVERSIZED,
        phase1_action=WasteAction.DOWNSIZE,
        action=WasteAction.DOWNSIZE,
    )
    return [phase1], [phase2]


def _s3_inputs():
    return [
        S3FindingResult(
            bucket_name="bucket-a",
            action=S3Action.RECOMMEND_LIFECYCLE,
            waste_type=S3WasteType.MISSING_LIFECYCLE,
        )
    ]


class TestPhase3LLMTerraformContext(unittest.TestCase):
    @patch("phase3.llm_phase3._import_iac_eval", return_value=_fake_iac_eval())
    @patch("phase3.llm_phase3.resolve_terraform_bundle")
    def test_run_without_terraform_source_keeps_empty_context(self, resolve_bundle, _import_eval) -> None:
        with patch.dict(os.environ, {}, clear=True):
            output = run_phase3_llm([], [], _s3_inputs(), model_key="unit-test")

        resolve_bundle.assert_not_called()
        self.assertEqual(output["terraform_source"]["file_count"], 0)
        self.assertEqual(output["terraform_source"]["warnings"], [])
        self.assertEqual(output["runs"][0]["scenario"]["current_terraform"], "")

    @patch("phase3.llm_phase3._import_iac_eval", return_value=_fake_iac_eval())
    @patch("phase3.llm_phase3.resolve_terraform_bundle")
    def test_resolved_bundle_is_passed_into_ec2_and_s3_scenarios(self, resolve_bundle, _import_eval) -> None:
        source = TerraformSource(
            repo_url="https://github.com/Nour-Ben-Hadid/finops-infra.git",
            ref="feature",
            subdir="terraform/prod",
        )
        resolve_bundle.return_value = TerraformBundle(
            source=source,
            owner="Nour-Ben-Hadid",
            repo="finops-infra",
            files={"terraform/prod/main.tf": 'resource "aws_instance" "app" {}'},
            prompt_bundle="### FILE: terraform/prod/main.tf\n```hcl\nresource {}\n```",
            total_bytes=58,
            warnings=["partial source warning"],
        )
        ec2_phase1, ec2_phase2 = _ec2_inputs()

        with patch.dict(os.environ, {"PHASE3_EVALUATE_S3": "1"}, clear=True):
            output = run_phase3_llm(
                ec2_phase1,
                ec2_phase2,
                _s3_inputs(),
                model_key="unit-test",
                terraform_source={
                    "repo_url": source.repo_url,
                    "ref": source.ref,
                    "subdir": source.subdir,
                },
            )

        resolve_bundle.assert_called_once_with(source)
        scenarios = {run["scenario_type"]: run["scenario"] for run in output["runs"]}
        self.assertEqual(scenarios["ec2"]["current_terraform"], resolve_bundle.return_value.prompt_bundle)
        self.assertEqual(scenarios["s3"]["current_terraform"], resolve_bundle.return_value.prompt_bundle)
        self.assertEqual(output["terraform_source"]["files"], ["terraform/prod/main.tf"])
        self.assertEqual(output["terraform_source"]["warnings"], ["partial source warning"])
        self.assertNotIn("prompt_bundle", output["terraform_source"])

    @patch("phase3.llm_phase3._import_iac_eval", return_value=_fake_iac_eval())
    @patch("phase3.llm_phase3.resolve_terraform_bundle", side_effect=RuntimeError("network unavailable"))
    def test_fetch_failure_adds_warning_and_still_runs(self, _resolve_bundle, _import_eval) -> None:
        with patch.dict(os.environ, {}, clear=True):
            output = run_phase3_llm(
                [],
                [],
                _s3_inputs(),
                model_key="unit-test",
                terraform_source={"repo_url": "https://github.com/owner/repo.git"},
            )

        self.assertEqual(output["runs"][0]["scenario"]["current_terraform"], "")
        self.assertEqual(output["terraform_source"]["file_count"], 0)
        self.assertEqual(
            output["terraform_source"]["warnings"],
            ["Failed to resolve Terraform bundle: network unavailable"],
        )

    @patch("phase3.llm_phase3._import_iac_eval", return_value=_fake_downsize_iac_eval())
    @patch("phase3.llm_phase3.resolve_terraform_bundle")
    def test_ec2_downsize_generates_structured_main_tf_patch(self, resolve_bundle, _import_eval) -> None:
        main_tf = """
module "i_001" {
  source        = "./modules/ec2"
  instance_id   = "i-001"
  instance_type = "c5.xlarge"
  role          = "steady"
}
"""
        source = TerraformSource(repo_url="https://github.com/owner/repo.git", ref="main", subdir="")
        resolve_bundle.return_value = TerraformBundle(
            source=source,
            owner="owner",
            repo="repo",
            files={"main.tf": main_tf},
            prompt_bundle=f"### FILE: main.tf\n```hcl\n{main_tf}\n```",
            total_bytes=len(main_tf),
            warnings=[],
        )

        with patch.dict(os.environ, {"PHASE3_EC2_LLM_VALIDATION": "1"}, clear=True):
            output = run_phase3_llm(
                [
                    {
                        "resource_id": 1,
                        "resource_name": "i-001",
                        "action": "DOWNSIZE",
                        "recommended_type": "c5.medium",
                    }
                ],
                [
                    {
                        "resource_id": 1,
                        "instance_name": "i-001",
                        "action": "DOWNSIZE",
                        "recommended_type": "c5.medium",
                        "instance_type": "c5.xlarge",
                    }
                ],
                [],
                model_key="unit-test",
                terraform_source={"repo_url": source.repo_url},
            )

        self.assertEqual([run["scenario_type"] for run in output["runs"]], ["ec2", "terraform_patch"])
        self.assertIn('instance_id   = "i-001"', output["runs"][0]["scenario"]["current_terraform"])
        self.assertNotIn("unexpected.tf", [item["file_path"] for item in output["patch_preview"]["modified_files"]])
        self.assertEqual(output["patch_preview"]["modified_files"][0]["file_path"], "main.tf")
        self.assertIn('instance_type = "c5.large"', output["patch_preview"]["modified_files"][0]["new_content"])
        self.assertIn('instance_type = "c5.xlarge"', output["patch_preview"]["modified_files"][0]["original_content"])

    @patch("phase3.llm_phase3._import_iac_eval", return_value=_fake_downsize_iac_eval())
    @patch("phase3.llm_phase3.resolve_terraform_bundle")
    def test_downsize_without_target_gets_one_size_down_for_llm_validation(self, resolve_bundle, _import_eval) -> None:
        main_tf = """
module "i_001" {
  source        = "./modules/ec2"
  instance_id   = "i-001"
  instance_type = "c5.xlarge"
  role          = "steady"
}
"""
        source = TerraformSource(repo_url="https://github.com/owner/repo.git", ref="main", subdir="")
        resolve_bundle.return_value = TerraformBundle(
            source=source,
            owner="owner",
            repo="repo",
            files={"main.tf": main_tf},
            prompt_bundle=f"### FILE: main.tf\n```hcl\n{main_tf}\n```",
            total_bytes=len(main_tf),
            warnings=[],
        )

        with patch.dict(os.environ, {"PHASE3_EC2_LLM_VALIDATION": "1"}, clear=True):
            output = run_phase3_llm(
                [
                    {
                        "resource_id": 1,
                        "resource_name": "i-001",
                        "action": "STOP",
                        "current_instance_type": "c5.xlarge",
                    }
                ],
                [
                    {
                        "resource_id": 1,
                        "instance_name": "i-001",
                        "action": "DOWNSIZE",
                        "instance_type": "c5.xlarge",
                    }
                ],
                [],
                model_key="unit-test",
                terraform_source={"repo_url": source.repo_url},
            )

        resource = output["runs"][0]["scenario"]["flagged_resources"][0]
        self.assertEqual(resource["agent2_decision"]["recommended_type"], "c5.large")
        self.assertEqual(output["runs"][0]["llm"]["parsed"]["decision_summary"]["decided_by"], "AGENT_VALIDATED")
        self.assertIn('instance_type = "c5.large"', output["patch_preview"]["modified_files"][0]["new_content"])


if __name__ == "__main__":
    unittest.main()
