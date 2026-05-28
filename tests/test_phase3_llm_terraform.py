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


class _FakeRunners:
    class ContextTooLargeError(Exception):
        pass

    @staticmethod
    def get_runner(model_cfg, api_keys):
        return _FakeRunner()


def _fake_iac_eval():
    config = SimpleNamespace(MODELS={"unit-test": {"provider": "fake", "model_id": "fake-model"}})
    return config, _FakePromptBuilder, _FakeRunners


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
        self.assertGreater(output["runs"][0]["prompt_token_estimate"], 0)
        self.assertEqual(
            output["code_generation_safety"]["max_prompt_token_estimate"],
            output["runs"][0]["prompt_token_estimate"],
        )
        self.assertFalse(output["code_generation_safety"]["use_static_patch_fallback"])

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

        with patch.dict(os.environ, {}, clear=True):
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
        self.assertTrue(all("prompt_token_estimate" in run for run in output["runs"]))
        self.assertEqual(output["code_generation_safety"]["safe_codegen_token_limit"], 6000)
        self.assertFalse(output["code_generation_safety"]["context_fallback_was_used"])

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
        self.assertFalse(output["code_generation_safety"]["terraform_context_too_large"])

    @patch("phase3.llm_phase3._import_iac_eval", return_value=_fake_iac_eval())
    @patch("phase3.llm_phase3.resolve_terraform_bundle")
    def test_codegen_safety_flags_large_prompt_and_terraform_context_warning(self, resolve_bundle, _import_eval) -> None:
        source = TerraformSource(
            repo_url="https://github.com/Nour-Ben-Hadid/finops-infra.git",
            ref="main",
            subdir="",
        )
        resolve_bundle.return_value = TerraformBundle(
            source=source,
            owner="Nour-Ben-Hadid",
            repo="finops-infra",
            files={"main.tf": 'resource "aws_instance" "app" {}'},
            prompt_bundle="### FILE: main.tf\n```hcl\nresource {}\n```",
            total_bytes=42,
            warnings=[
                "Terraform prompt bundle exceeded PHASE3_TERRAFORM_MAX_BYTES=1; remaining files were not included."
            ],
        )

        with patch.dict(os.environ, {"PHASE3_LLM_CODEGEN_SAFE_TOKENS": "1"}, clear=True):
            output = run_phase3_llm(
                [],
                [],
                _s3_inputs(),
                model_key="unit-test",
                terraform_source={"repo_url": source.repo_url},
            )

        safety = output["code_generation_safety"]
        self.assertEqual(safety["safe_codegen_token_limit"], 1)
        self.assertGreater(safety["max_prompt_token_estimate"], 1)
        self.assertTrue(safety["terraform_context_too_large"])
        self.assertTrue(safety["use_static_patch_fallback"])
        self.assertEqual(
            safety["reason"],
            "Prompt/context exceeded the safe LLM code-generation envelope.",
        )


if __name__ == "__main__":
    unittest.main()
