import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from phase3.local_patch import (
    apply_patch_plan_locally,
    apply_patch_plan_to_directory,
    run_terraform_fmt,
    run_terraform_validate,
    validate_patch_plan,
)
from phase3.patch_schema import ModifiedFile, PatchPlan


def _plan(*files: ModifiedFile) -> PatchPlan:
    return PatchPlan(
        modified_files=list(files),
        pr_title="Patch Terraform",
        pr_description="Generated patch.",
        warnings=[],
    )


class TestValidatePatchPlan(unittest.TestCase):
    def test_rejects_empty_patch_plan(self) -> None:
        self.assertEqual(validate_patch_plan(_plan(), {}), ["No modified files to apply."])

    def test_rejects_non_terraform_file(self) -> None:
        errors = validate_patch_plan(_plan(ModifiedFile("README.md", "updated")), {"README.md": "original"})
        self.assertTrue(any("Only .tf files" in error for error in errors))

    def test_rejects_absolute_paths(self) -> None:
        for file_path in (r"C:\temp\x.tf", "/tmp/x.tf"):
            with self.subTest(file_path=file_path):
                errors = validate_patch_plan(_plan(ModifiedFile(file_path, "resource {}")), {})
                self.assertTrue(any("Absolute file path" in error for error in errors))

    def test_rejects_path_traversal(self) -> None:
        for file_path in ("../outside.tf", "modules/../../outside.tf"):
            with self.subTest(file_path=file_path):
                errors = validate_patch_plan(_plan(ModifiedFile(file_path, "resource {}")), {})
                self.assertTrue(any("Path traversal" in error for error in errors))

    def test_rejects_terraform_and_git_directories(self) -> None:
        for file_path in (".terraform/modules/x.tf", "modules/.terraform/x.tf", ".git/x.tf"):
            with self.subTest(file_path=file_path):
                errors = validate_patch_plan(_plan(ModifiedFile(file_path, "resource {}")), {})
                self.assertTrue(any("Blocked Terraform file path" in error for error in errors))

    def test_rejects_state_files(self) -> None:
        for file_path in ("terraform.tfstate", "prod/terraform.tfstate", "prod/terraform.tfstate.backup"):
            with self.subTest(file_path=file_path):
                errors = validate_patch_plan(_plan(ModifiedFile(file_path, "state")), {file_path: "old"})
                self.assertTrue(any("Terraform state file" in error for error in errors))

    def test_rejects_empty_new_content(self) -> None:
        errors = validate_patch_plan(_plan(ModifiedFile("main.tf", " \n")), {"main.tf": "old"})
        self.assertTrue(any("New content is empty" in error for error in errors))

    def test_rejects_unknown_file_when_new_files_disabled(self) -> None:
        with patch.dict(os.environ, {"PHASE3_ALLOW_NEW_TF_FILES": "0"}, clear=False):
            errors = validate_patch_plan(_plan(ModifiedFile("new.tf", "resource {}")), {"main.tf": "old"})
        self.assertIn("File not in original Terraform bundle: new.tf", errors)

    def test_accepts_known_terraform_file(self) -> None:
        with patch.dict(os.environ, {"PHASE3_ALLOW_NEW_TF_FILES": "0"}, clear=False):
            errors = validate_patch_plan(_plan(ModifiedFile("main.tf", "resource {}")), {"main.tf": "old"})
        self.assertEqual(errors, [])

    def test_enforces_max_files(self) -> None:
        plan = _plan(ModifiedFile("main.tf", "one"), ModifiedFile("variables.tf", "two"))
        with patch.dict(os.environ, {"PHASE3_PATCH_MAX_FILES": "1", "PHASE3_ALLOW_NEW_TF_FILES": "1"}, clear=False):
            errors = validate_patch_plan(plan, {})
        self.assertIn("Too many modified files: 2 > 1", errors)


class TestApplyPatchPlan(unittest.TestCase):
    def test_writes_full_new_content_with_one_trailing_newline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = Path(tmp)
            target = repo_dir / "main.tf"
            target.write_text("old\n", encoding="utf-8")
            plan = _plan(ModifiedFile("main.tf", "resource \"aws_instance\" \"app\" {}\n\n"))

            changed = apply_patch_plan_to_directory(repo_dir, plan, {"main.tf": "old\n"})

            self.assertEqual(changed, ["main.tf"])
            self.assertEqual(target.read_text(encoding="utf-8"), 'resource "aws_instance" "app" {}\n')

    def test_does_not_write_outside_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo_dir = base / "repo"
            repo_dir.mkdir()
            outside = base / "outside.tf"
            plan = _plan(ModifiedFile("../outside.tf", "escaped"))

            with self.assertRaises(ValueError):
                apply_patch_plan_to_directory(repo_dir, plan, {}, allow_new_files=True)

            self.assertFalse(outside.exists())

    def test_allows_new_file_only_when_explicitly_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = Path(tmp)
            plan = _plan(ModifiedFile("modules/new/main.tf", "resource {}"))

            changed = apply_patch_plan_to_directory(repo_dir, plan, {}, allow_new_files=True)

            self.assertEqual(changed, ["modules/new/main.tf"])
            self.assertEqual((repo_dir / "modules" / "new" / "main.tf").read_text(encoding="utf-8"), "resource {}\n")


class TestTerraformCommands(unittest.TestCase):
    @patch("phase3.local_patch.subprocess.run", side_effect=FileNotFoundError("terraform missing"))
    def test_fmt_handles_missing_terraform(self, _run) -> None:
        warning = run_terraform_fmt(Path("."))
        self.assertIn("terraform fmt could not run", warning)

    @patch("phase3.local_patch.subprocess.run")
    def test_validate_is_skipped_by_default(self, run) -> None:
        with patch.dict(os.environ, {}, clear=True):
            warning = run_terraform_validate(Path("."))

        self.assertIsNone(warning)
        run.assert_not_called()

    @patch("phase3.local_patch.subprocess.run")
    def test_validate_runs_init_and_validate_when_enabled(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with patch.dict(os.environ, {"PHASE3_RUN_TERRAFORM_VALIDATE": "1"}, clear=False):
            warning = run_terraform_validate(Path("."))

        self.assertIsNone(warning)
        self.assertEqual(run.call_args_list[0].args[0], ["terraform", "init", "-backend=false"])
        self.assertEqual(run.call_args_list[1].args[0], ["terraform", "validate"])

    @patch("phase3.local_patch.run_terraform_validate", return_value="validate warning")
    @patch("phase3.local_patch.run_terraform_fmt", return_value="fmt warning")
    def test_local_wrapper_returns_non_fatal_command_warnings(self, _fmt, _validate) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = Path(tmp)
            (repo_dir / "main.tf").write_text("old\n", encoding="utf-8")

            result = apply_patch_plan_locally(
                repo_dir,
                _plan(ModifiedFile("main.tf", "new")),
                {"main.tf": "old\n"},
            )

        self.assertTrue(result.applied)
        self.assertEqual(result.changed_files, ["main.tf"])
        self.assertEqual(result.warnings, ["fmt warning", "validate warning"])
        self.assertEqual(result.errors, [])


if __name__ == "__main__":
    unittest.main()
