"""Integration-style tests for Phase 3 patch planning and PR orchestration.

The suite runs Phase 3 with mocked LLM/Terraform and GitHub collaborators to
verify disabled-PR summaries, enabled PR creation using original files,
suppression when no modified files exist, non-fatal PR exceptions, and compact
patch-plan summaries that avoid duplicating full Terraform contents.
"""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from phase3.github_pr import PullRequestResult
from phase3.github_terraform import TerraformBundle, TerraformSource
from phase3.llm_phase3 import run_phase3_llm
from phase3.patch_schema import ModifiedFile, PatchPlan


class _FakePromptBuilder:
    @staticmethod
    def build_prompt(scenario):
        return "system", f"user:{scenario.get('scenario_id')}"


class _FakeRunner:
    def run(self, system_prompt, user_prompt):
        return {"parsed": {"verdict": "OPTIMAL"}}


class _FakeRunners:
    @staticmethod
    def get_runner(model_cfg, api_keys):
        return _FakeRunner()


def _fake_iac_eval():
    config = SimpleNamespace(MODELS={"unit-test": {"provider": "fake", "model_id": "fake-model"}})
    return config, _FakePromptBuilder, _FakeRunners


def _source() -> TerraformSource:
    return TerraformSource(repo_url="https://github.com/owner/repo.git", ref="main", subdir="")


def _bundle() -> TerraformBundle:
    source = _source()
    return TerraformBundle(
        source=source,
        owner="owner",
        repo="repo",
        files={"main.tf": "original terraform"},
        prompt_bundle="### FILE: main.tf\n```hcl\noriginal terraform\n```",
        total_bytes=50,
        warnings=[],
    )


def _patch_plan() -> PatchPlan:
    return PatchPlan(
        modified_files=[ModifiedFile("main.tf", "patched terraform")],
        pr_title="Optimize Terraform",
        pr_description="Generated patch.",
        warnings=[],
    )


class TestPhase3PRIntegration(unittest.TestCase):
    @patch("phase3.llm_phase3._import_iac_eval", return_value=_fake_iac_eval())
    @patch("phase3.llm_phase3.resolve_terraform_bundle", return_value=_bundle())
    @patch("phase3.llm_phase3.extract_patch_plan", return_value=_patch_plan())
    @patch("phase3.llm_phase3.create_pull_request_from_patch_plan")
    def test_pr_disabled_records_summary_without_creation(
        self,
        create_pull_request,
        _extract_plan,
        _resolve_bundle,
        _import_eval,
    ) -> None:
        with patch.dict(os.environ, {"PHASE3_CREATE_PR": "0"}, clear=True):
            output = run_phase3_llm(
                [],
                [],
                [],
                model_key="unit-test",
                terraform_source={"repo_url": _source().repo_url},
            )

        create_pull_request.assert_not_called()
        self.assertIn("patch_plan", output)
        self.assertFalse(output["pull_request"]["created"])
        self.assertIn("disabled", output["pull_request"]["reason"])

    @patch("phase3.llm_phase3._import_iac_eval", return_value=_fake_iac_eval())
    @patch("phase3.llm_phase3.resolve_terraform_bundle", return_value=_bundle())
    @patch("phase3.llm_phase3.extract_patch_plan", return_value=_patch_plan())
    @patch("phase3.llm_phase3.create_pull_request_from_patch_plan")
    def test_enabled_pr_creation_uses_patch_plan_and_original_files(
        self,
        create_pull_request,
        _extract_plan,
        _resolve_bundle,
        _import_eval,
    ) -> None:
        create_pull_request.return_value = PullRequestResult(
            created=True,
            branch_name="finops/phase3-1",
            pr_url="https://github.com/owner/repo/pull/1",
            changed_files=["main.tf"],
            warnings=[],
            errors=[],
        )
        with patch.dict(os.environ, {"PHASE3_CREATE_PR": "1"}, clear=True):
            output = run_phase3_llm(
                [],
                [],
                [],
                model_key="unit-test",
                terraform_source={"repo_url": _source().repo_url, "ref": "main", "subdir": ""},
            )

        create_pull_request.assert_called_once_with(_source(), _patch_plan(), {"main.tf": "original terraform"})
        self.assertTrue(output["pull_request"]["created"])
        self.assertEqual(output["pull_request"]["pr_url"], "https://github.com/owner/repo/pull/1")

    @patch("phase3.llm_phase3._import_iac_eval", return_value=_fake_iac_eval())
    @patch("phase3.llm_phase3.resolve_terraform_bundle", return_value=_bundle())
    @patch(
        "phase3.llm_phase3.extract_patch_plan",
        return_value=PatchPlan([], "No change", "No change.", []),
    )
    @patch("phase3.llm_phase3.create_pull_request_from_patch_plan")
    def test_enabled_pr_is_not_created_without_modified_files(
        self,
        create_pull_request,
        _extract_plan,
        _resolve_bundle,
        _import_eval,
    ) -> None:
        with patch.dict(os.environ, {"PHASE3_CREATE_PR": "1"}, clear=True):
            output = run_phase3_llm(
                [],
                [],
                [],
                model_key="unit-test",
                terraform_source={"repo_url": _source().repo_url},
            )

        create_pull_request.assert_not_called()
        self.assertFalse(output["pull_request"]["created"])
        self.assertEqual(
            output["pull_request"]["reason"],
            "No modified files were returned by the LLM.",
        )

    @patch("phase3.llm_phase3._import_iac_eval", return_value=_fake_iac_eval())
    @patch("phase3.llm_phase3.resolve_terraform_bundle", return_value=_bundle())
    @patch("phase3.llm_phase3.extract_patch_plan", return_value=_patch_plan())
    @patch("phase3.llm_phase3.create_pull_request_from_patch_plan", side_effect=RuntimeError("PR unavailable"))
    def test_pr_exception_is_returned_without_crashing(
        self,
        _create_pull_request,
        _extract_plan,
        _resolve_bundle,
        _import_eval,
    ) -> None:
        with patch.dict(os.environ, {"PHASE3_CREATE_PR": "yes"}, clear=True):
            output = run_phase3_llm(
                [],
                [],
                [],
                model_key="unit-test",
                terraform_source={"repo_url": _source().repo_url},
            )

        self.assertFalse(output["pull_request"]["created"])
        self.assertEqual(output["pull_request"]["errors"], ["PR unavailable"])

    @patch("phase3.llm_phase3._import_iac_eval", return_value=_fake_iac_eval())
    @patch("phase3.llm_phase3.extract_patch_plan", return_value=_patch_plan())
    @patch("phase3.llm_phase3.create_pull_request_from_patch_plan")
    def test_patch_plan_summary_does_not_duplicate_content(
        self,
        create_pull_request,
        _extract_plan,
        _import_eval,
    ) -> None:
        with patch.dict(os.environ, {}, clear=True):
            output = run_phase3_llm([], [], [], model_key="unit-test")

        create_pull_request.assert_not_called()
        file_summary = output["patch_plan"]["modified_files"][0]
        self.assertEqual(file_summary["file_path"], "main.tf")
        self.assertEqual(file_summary["new_content_length"], len("patched terraform"))
        self.assertNotIn("new_content", file_summary)


if __name__ == "__main__":
    unittest.main()
