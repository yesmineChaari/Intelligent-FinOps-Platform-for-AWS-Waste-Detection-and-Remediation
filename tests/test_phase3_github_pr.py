"""Unit tests for the optional Phase 3 GitHub pull-request workflow.

These tests exercise token requirements, patch-plan validation before any Git
or GitHub action, authenticated repository URL generation, branch naming,
successful draft PR creation, no-change handling, and honoring the configured
draft pull-request flag while mocking external side effects.
"""

import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from phase3.github_pr import (
    _authenticated_repo_url,
    _build_branch_name,
    create_pull_request_from_patch_plan,
)
from phase3.github_terraform import TerraformSource
from phase3.patch_schema import ModifiedFile, PatchPlan


class GithubPullRequestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = TerraformSource(
            repo_url="https://github.com/owner/repo.git",
            ref="main",
        )
        self.plan = PatchPlan(
            modified_files=[ModifiedFile("main.tf", 'resource "x" "y" {}')],
            pr_title="Optimize Terraform",
            pr_description="Update provisioned infrastructure.",
            warnings=[],
        )
        self.original_files = {"main.tf": 'resource "x" "y" {}'}

    @staticmethod
    def _subprocess_result(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        stdout = " M main.tf\n" if cmd == ["git", "status", "--porcelain"] else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    def test_missing_github_token_returns_error(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            result = create_pull_request_from_patch_plan(self.source, self.plan, self.original_files)

        self.assertFalse(result.created)
        self.assertIn("GITHUB_TOKEN is required to create a PR.", result.errors)

    def test_invalid_patch_plan_does_not_run_commands_or_github(self) -> None:
        plan = PatchPlan(
            modified_files=[ModifiedFile("README.md", "text")],
            pr_title="Invalid",
            pr_description="Invalid",
            warnings=[],
        )
        with (
            patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}, clear=True),
            patch("phase3.github_pr.subprocess.run") as run,
            patch("phase3.github_pr.Github") as github,
        ):
            result = create_pull_request_from_patch_plan(
                self.source,
                plan,
                {"README.md": "text"},
            )

        self.assertFalse(result.created)
        self.assertTrue(result.errors)
        run.assert_not_called()
        github.assert_not_called()

    def test_no_modified_files_returns_error(self) -> None:
        plan = PatchPlan([], "", "", [])
        result = create_pull_request_from_patch_plan(self.source, plan, self.original_files)

        self.assertFalse(result.created)
        self.assertEqual(result.errors, ["No modified files to commit."])

    def test_authenticated_repo_url_injects_token_for_https(self) -> None:
        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}, clear=True):
            url = _authenticated_repo_url("https://github.com/owner/repo.git")

        self.assertTrue(url.startswith("https://x-access-token:test-token@github.com/"))

    def test_branch_name_uses_configured_prefix(self) -> None:
        with (
            patch.dict(os.environ, {"PHASE3_PR_BRANCH_PREFIX": "finops/test"}, clear=True),
            patch("phase3.github_pr.time.time", return_value=1770000000),
        ):
            branch_name = _build_branch_name()

        self.assertEqual(branch_name, "finops/test-1770000000")

    def test_successful_pr_flow(self) -> None:
        github = MagicMock()
        github.return_value.get_repo.return_value.create_pull.return_value.html_url = (
            "https://github.com/owner/repo/pull/7"
        )
        with (
            patch.dict(os.environ, {"GITHUB_TOKEN": "test-token", "PHASE3_PR_DRAFT": "1"}, clear=True),
            patch("phase3.github_pr.tempfile.mkdtemp", return_value="C:/tmp/pfa-pr-test"),
            patch("phase3.github_pr.shutil.rmtree") as cleanup,
            patch("phase3.github_pr.subprocess.run", side_effect=self._subprocess_result) as run,
            patch("phase3.github_pr.apply_patch_plan_to_directory", return_value=["main.tf"]),
            patch("phase3.github_pr.run_terraform_fmt", return_value=None),
            patch("phase3.github_pr.run_terraform_validate", return_value=None),
            patch("phase3.github_pr.Github", github),
            patch("phase3.github_pr.time.time", return_value=1770000000),
        ):
            result = create_pull_request_from_patch_plan(self.source, self.plan, self.original_files)

        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn(
            [
                "git",
                "clone",
                "--branch",
                "main",
                "https://x-access-token:test-token@github.com/owner/repo.git",
                "repo",
            ],
            commands,
        )
        self.assertIn(["git", "checkout", "-b", "finops/phase3-1770000000"], commands)
        self.assertIn(["git", "status", "--porcelain"], commands)
        self.assertIn(["git", "add", "."], commands)
        self.assertIn(["git", "commit", "-m", "Optimize Terraform"], commands)
        self.assertIn(["git", "push", "origin", "finops/phase3-1770000000"], commands)
        github.assert_called_once_with("test-token")
        github.return_value.get_repo.assert_called_once_with("owner/repo")
        github.return_value.get_repo.return_value.create_pull.assert_called_once_with(
            title="Optimize Terraform",
            body="Update provisioned infrastructure.",
            head="finops/phase3-1770000000",
            base="main",
            draft=True,
        )
        self.assertTrue(result.created)
        self.assertEqual(result.pr_url, "https://github.com/owner/repo/pull/7")
        self.assertEqual(result.changed_files, ["main.tf"])
        cleanup.assert_called_once_with(Path("C:/tmp/pfa-pr-test"), ignore_errors=True)

    def test_no_git_changes_skips_pr_creation(self) -> None:
        def no_status_changes(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with (
            patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}, clear=True),
            patch("phase3.github_pr.tempfile.mkdtemp", return_value="C:/tmp/pfa-pr-test"),
            patch("phase3.github_pr.shutil.rmtree"),
            patch("phase3.github_pr.subprocess.run", side_effect=no_status_changes),
            patch("phase3.github_pr.apply_patch_plan_to_directory", return_value=["main.tf"]),
            patch("phase3.github_pr.run_terraform_fmt", return_value=None),
            patch("phase3.github_pr.run_terraform_validate", return_value=None),
            patch("phase3.github_pr.Github") as github,
        ):
            result = create_pull_request_from_patch_plan(self.source, self.plan, self.original_files)

        self.assertFalse(result.created)
        self.assertEqual(result.changed_files, [])
        self.assertIn("No git changes after applying patch.", result.errors)
        github.assert_not_called()

    def test_draft_pr_flag_is_respected(self) -> None:
        for flag, expected in (("1", True), ("0", False)):
            with self.subTest(flag=flag):
                github = MagicMock()
                github.return_value.get_repo.return_value.create_pull.return_value.html_url = (
                    "https://github.com/owner/repo/pull/8"
                )
                with (
                    patch.dict(
                        os.environ,
                        {"GITHUB_TOKEN": "test-token", "PHASE3_PR_DRAFT": flag},
                        clear=True,
                    ),
                    patch("phase3.github_pr.tempfile.mkdtemp", return_value="C:/tmp/pfa-pr-test"),
                    patch("phase3.github_pr.shutil.rmtree"),
                    patch("phase3.github_pr.subprocess.run", side_effect=self._subprocess_result),
                    patch("phase3.github_pr.apply_patch_plan_to_directory", return_value=["main.tf"]),
                    patch("phase3.github_pr.run_terraform_fmt", return_value=None),
                    patch("phase3.github_pr.run_terraform_validate", return_value=None),
                    patch("phase3.github_pr.Github", github),
                ):
                    result = create_pull_request_from_patch_plan(
                        self.source,
                        self.plan,
                        self.original_files,
                    )

                self.assertTrue(result.created)
                create_pull = github.return_value.get_repo.return_value.create_pull
                self.assertEqual(create_pull.call_args.kwargs["draft"], expected)


if __name__ == "__main__":
    unittest.main()
