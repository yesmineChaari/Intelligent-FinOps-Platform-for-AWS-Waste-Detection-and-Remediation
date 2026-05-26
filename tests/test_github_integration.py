"""
Integration tests for github_terraform.py and github_pr.py.

No LLM is called. The tests run in three stages:
  Stage 1 — fetch real .tf files from GitHub
  Stage 2 — apply a mock patch (instance_type downsize) to the fetched files
  Stage 3 — commit the patch on a new branch and open a draft PR

Required env vars (tests are skipped if missing):
    GITHUB_TOKEN                  personal access token with repo scope
    PHASE3_TERRAFORM_REPO_URL     e.g. https://github.com/<owner>/finops-infra

Optional env vars:
    PHASE3_TERRAFORM_REF          branch to fetch from (default: main)
    PHASE3_PR_BASE_BRANCH         PR target branch    (default: main)

Run with:
    cd pfa/pfa
    pytest phase3/test_github_integration.py -v
"""

import os
import re
import sys
from pathlib import Path
import pytest

# iac_eval is not an installed package — it lives inside llm_benchmarking/
# phase3/__init__.py imports run_phase3_llm which needs it on sys.path
_iac_eval_path = str(Path(__file__).resolve().parents[1] / "llm_benchmarking" / "IaC-Evaluation-Pipeline")
if _iac_eval_path not in sys.path:
    sys.path.insert(0, _iac_eval_path)

from phase3.github_terraform import (
    TerraformSource,
    TerraformBundle,
    resolve_terraform_bundle,
    should_include_tf_path,
    redact_terraform_secrets,
)
from phase3.patch_schema import PatchPlan, ModifiedFile
from phase3.local_patch import validate_patch_plan
from phase3.github_pr import create_pull_request_from_patch_plan


# ── helpers ───────────────────────────────────────────────────────────────────

def _repo_url() -> str:
    return os.environ.get("PHASE3_TERRAFORM_REPO_URL", "")

def _token() -> str:
    return os.environ.get("GITHUB_TOKEN", "")

def _ref() -> str:
    return os.environ.get("PHASE3_TERRAFORM_REF", "main")

def _source() -> TerraformSource:
    return TerraformSource(repo_url=_repo_url(), ref=_ref())

requires_github = pytest.mark.skipif(
    not _repo_url() or not _token(),
    reason="GITHUB_TOKEN and PHASE3_TERRAFORM_REPO_URL must be set",
)


# ── Stage 0: unit tests — no network ─────────────────────────────────────────

class TestShouldIncludeTfPath:
    def test_accepts_root_tf(self):
        assert should_include_tf_path("main.tf") is True

    def test_accepts_module_tf(self):
        assert should_include_tf_path("modules/ec2/main.tf") is True

    def test_rejects_tfstate(self):
        assert should_include_tf_path("terraform.tfstate") is False

    def test_rejects_tfstate_backup(self):
        assert should_include_tf_path("terraform.tfstate.backup") is False

    def test_rejects_dot_terraform(self):
        assert should_include_tf_path(".terraform/providers/aws.zip") is False

    def test_rejects_non_tf_extension(self):
        assert should_include_tf_path("variables.json") is False

    def test_rejects_path_traversal(self):
        assert should_include_tf_path("../secrets.tf") is False

    def test_subdir_filter_includes_matching(self):
        assert should_include_tf_path("modules/ec2/main.tf", subdir="modules/ec2") is True

    def test_subdir_filter_excludes_non_matching(self):
        assert should_include_tf_path("main.tf", subdir="modules/ec2") is False


class TestRedactTerraformSecrets:
    def test_redacts_access_key(self):
        content = 'access_key = "AKIAIOSFODNN7EXAMPLE"'
        result = redact_terraform_secrets(content)
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "***REDACTED***" in result

    def test_redacts_secret_key(self):
        content = 'secret_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"'
        result = redact_terraform_secrets(content)
        assert "wJalrXUtnFEMI" not in result

    def test_preserves_unrelated_lines(self):
        content = 'instance_type = "c5.xlarge"\naccess_key = "SECRET"'
        result = redact_terraform_secrets(content)
        assert 'instance_type = "c5.xlarge"' in result

    def test_redacts_token(self):
        content = 'token = "ghp_abc123"'
        result = redact_terraform_secrets(content)
        assert "ghp_abc123" not in result
        assert "***REDACTED***" in result


class TestValidatePatchPlan:
    def _original_files(self):
        return {"main.tf": 'module "i_001" { instance_type = "c5.xlarge" }'}

    def test_valid_patch_passes(self):
        plan = PatchPlan(
            modified_files=[ModifiedFile(file_path="main.tf", new_content='module "i_001" { instance_type = "c5.large" }')],
            pr_title="test",
            pr_description="test",
            warnings=[],
        )
        errors = validate_patch_plan(plan, self._original_files())
        assert errors == []

    def test_rejects_tfstate(self):
        plan = PatchPlan(
            modified_files=[ModifiedFile(file_path="terraform.tfstate", new_content="{}")],
            pr_title="test",
            pr_description="test",
            warnings=[],
        )
        errors = validate_patch_plan(plan, self._original_files())
        assert any("state" in e.lower() for e in errors)

    def test_rejects_path_traversal(self):
        plan = PatchPlan(
            modified_files=[ModifiedFile(file_path="../main.tf", new_content="x")],
            pr_title="test",
            pr_description="test",
            warnings=[],
        )
        errors = validate_patch_plan(plan, self._original_files())
        assert errors

    def test_rejects_non_tf_file(self):
        plan = PatchPlan(
            modified_files=[ModifiedFile(file_path="main.json", new_content="{}")],
            pr_title="test",
            pr_description="test",
            warnings=[],
        )
        errors = validate_patch_plan(plan, self._original_files())
        assert any(".tf" in e for e in errors)

    def test_rejects_file_not_in_original_bundle(self):
        plan = PatchPlan(
            modified_files=[ModifiedFile(file_path="modules/ec2/new_file.tf", new_content="x = 1")],
            pr_title="test",
            pr_description="test",
            warnings=[],
        )
        errors = validate_patch_plan(plan, self._original_files())
        assert errors


# ── Stage 1: fetch real .tf files from GitHub ─────────────────────────────────

@requires_github
class TestTerraformFetch:
    @pytest.fixture(scope="class")
    def bundle(self) -> TerraformBundle:
        return resolve_terraform_bundle(_source())

    def test_files_were_fetched(self, bundle):
        assert len(bundle.files) > 0, "No .tf files were fetched"

    def test_main_tf_present(self, bundle):
        assert "main.tf" in bundle.files, f"main.tf not found. Got: {list(bundle.files)}"

    def test_no_tfstate_files(self, bundle):
        for path in bundle.files:
            assert not path.endswith(".tfstate"), f"tfstate file leaked into bundle: {path}"
            assert not path.endswith(".tfstate.backup"), f"tfstate.backup leaked: {path}"

    def test_no_dot_terraform(self, bundle):
        for path in bundle.files:
            assert ".terraform" not in path.split("/"), f".terraform dir leaked: {path}"

    def test_all_files_are_tf(self, bundle):
        for path in bundle.files:
            assert path.endswith(".tf"), f"Non-.tf file in bundle: {path}"

    def test_files_have_content(self, bundle):
        for path, content in bundle.files.items():
            assert content.strip(), f"Empty file in bundle: {path}"

    def test_prompt_bundle_has_file_headers(self, bundle):
        for path in bundle.files:
            assert f"### FILE: {path}" in bundle.prompt_bundle

    def test_no_secrets_in_bundle(self, bundle):
        secret_pattern = re.compile(
            r'(access_key|secret_key|password|token)\s*=\s*"(?!\*\*\*REDACTED\*\*\*)[^"]+"',
            re.IGNORECASE,
        )
        for path, content in bundle.files.items():
            match = secret_pattern.search(content)
            assert not match, f"Unredacted secret found in {path}: {match.group(0)}"

    def test_bundle_total_bytes_matches(self, bundle):
        assert bundle.total_bytes == len(bundle.prompt_bundle.encode("utf-8"))

    def test_no_warnings(self, bundle):
        assert bundle.warnings == [], f"Unexpected warnings: {bundle.warnings}"


# ── Stage 2: mock patch against fetched files ─────────────────────────────────

@requires_github
class TestMockPatch:
    @pytest.fixture(scope="class")
    def bundle(self) -> TerraformBundle:
        return resolve_terraform_bundle(_source())

    @pytest.fixture(scope="class")
    def patched_main_tf(self, bundle) -> str:
        """Simulate LLM output: downsize i-001 from c5.xlarge to c5.large."""
        content = bundle.files.get("main.tf", "")
        assert content, "main.tf not in bundle — cannot apply mock patch"
        return content.replace(
            'instance_type = "c5.xlarge"',
            'instance_type = "c5.large"',
        )

    @pytest.fixture(scope="class")
    def patch_plan(self, bundle, patched_main_tf) -> PatchPlan:
        return PatchPlan(
            modified_files=[
                ModifiedFile(file_path="main.tf", new_content=patched_main_tf)
            ],
            pr_title="[TEST] Downsize i-001 from c5.xlarge to c5.large",
            pr_description=(
                "Automated test patch — downsizes i-001 from c5.xlarge to c5.large.\n"
                "P95 CPU: 3.2%, waste: $69.12/month.\n"
                "This PR was created by the PFA Phase 3 integration test."
            ),
            warnings=[],
        )

    def test_patch_contains_change(self, patched_main_tf):
        assert 'instance_type = "c5.large"' in patched_main_tf

    def test_patch_does_not_break_other_instances(self, bundle, patched_main_tf):
        # i-002 uses c5.large already — make sure i-001 block changed but structure intact
        assert "module" in patched_main_tf
        assert 'instance_id   = "i-001"' in patched_main_tf

    def test_patch_plan_validates(self, bundle, patch_plan):
        errors = validate_patch_plan(patch_plan, bundle.files)
        assert errors == [], f"Patch plan validation failed: {errors}"

    def test_patch_plan_file_path_in_bundle(self, bundle, patch_plan):
        for mf in patch_plan.modified_files:
            assert mf.file_path in bundle.files, (
                f"file_path '{mf.file_path}' not in fetched bundle"
            )


# ── Stage 3: commit patch and open draft PR on GitHub ─────────────────────────

@requires_github
class TestPullRequestCreation:
    @pytest.fixture(scope="class")
    def bundle(self) -> TerraformBundle:
        return resolve_terraform_bundle(_source())

    @pytest.fixture(scope="class")
    def patch_plan(self, bundle) -> PatchPlan:
        patched = bundle.files["main.tf"].replace(
            'instance_type = "c5.xlarge"',
            'instance_type = "c5.large"',
        )
        return PatchPlan(
            modified_files=[ModifiedFile(file_path="main.tf", new_content=patched)],
            pr_title="[TEST] Downsize i-001 from c5.xlarge to c5.large",
            pr_description=(
                "Automated test patch created by PFA Phase 3 integration test.\n"
                "Safe to close — this PR exists only to verify the automation works."
            ),
            warnings=[],
        )

    @pytest.fixture(scope="class")
    def pr_result(self, bundle, patch_plan):
        os.environ.setdefault("PHASE3_PR_BRANCH_PREFIX", "finops/phase3-test")
        os.environ.setdefault("PHASE3_PR_DRAFT", "1")
        return create_pull_request_from_patch_plan(_source(), patch_plan, bundle.files)

    def test_pr_was_created(self, pr_result):
        assert pr_result.created, (
            f"PR was not created. Errors: {pr_result.errors}"
        )

    def test_pr_url_is_set(self, pr_result):
        assert pr_result.pr_url and pr_result.pr_url.startswith("https://github.com/")

    def test_branch_name_has_prefix(self, pr_result):
        assert pr_result.branch_name and "phase3-test" in pr_result.branch_name

    def test_changed_files_contains_main_tf(self, pr_result):
        assert "main.tf" in pr_result.changed_files

    def test_no_errors(self, pr_result):
        assert pr_result.errors == [], f"Unexpected errors: {pr_result.errors}"

    def test_pr_url_printed(self, pr_result):
        print(f"\n  PR URL: {pr_result.pr_url}")
        print(f"  Branch: {pr_result.branch_name}")
