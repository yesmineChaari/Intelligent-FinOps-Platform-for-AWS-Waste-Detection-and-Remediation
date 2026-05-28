import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PHASE3_DIR = ROOT / "agent2" / "phase3"
PACKAGE_NAME = "_phase3_static_patch_test"


def _load_static_patch_generator():
    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(PHASE3_DIR)]
    sys.modules[PACKAGE_NAME] = package

    schema_spec = importlib.util.spec_from_file_location(
        f"{PACKAGE_NAME}.patch_schema",
        PHASE3_DIR / "patch_schema.py",
    )
    assert schema_spec and schema_spec.loader
    schema_module = importlib.util.module_from_spec(schema_spec)
    sys.modules[schema_spec.name] = schema_module
    schema_spec.loader.exec_module(schema_module)

    generator_spec = importlib.util.spec_from_file_location(
        f"{PACKAGE_NAME}.static_patch_generator",
        PHASE3_DIR / "static_patch_generator.py",
    )
    assert generator_spec and generator_spec.loader
    generator_module = importlib.util.module_from_spec(generator_spec)
    sys.modules[generator_spec.name] = generator_module
    generator_spec.loader.exec_module(generator_module)
    return generator_module


static_patch_generator = _load_static_patch_generator()
build_static_patch_plan = static_patch_generator.build_static_patch_plan
patch_schema = sys.modules[f"{PACKAGE_NAME}.patch_schema"]
ModifiedFile = patch_schema.ModifiedFile
PatchPlan = patch_schema.PatchPlan


def _load_llm_phase3():
    converter = types.ModuleType(f"{PACKAGE_NAME}.converter")
    converter.build_ec2_scenario = lambda *args, **kwargs: {}
    converter.build_s3_scenario = lambda *args, **kwargs: {}
    sys.modules[converter.__name__] = converter

    github_pr = types.ModuleType(f"{PACKAGE_NAME}.github_pr")
    github_pr.create_pull_request_from_patch_plan = lambda *args, **kwargs: None
    sys.modules[github_pr.__name__] = github_pr

    github_terraform = types.ModuleType(f"{PACKAGE_NAME}.github_terraform")

    class TerraformSource:
        def __init__(self, repo_url: str, ref: str = "main", subdir: str = "") -> None:
            self.repo_url = repo_url
            self.ref = ref
            self.subdir = subdir

    github_terraform.TerraformSource = TerraformSource
    github_terraform.resolve_terraform_bundle = lambda *args, **kwargs: None
    sys.modules[github_terraform.__name__] = github_terraform

    llm_spec = importlib.util.spec_from_file_location(
        f"{PACKAGE_NAME}.llm_phase3",
        PHASE3_DIR / "llm_phase3.py",
    )
    assert llm_spec and llm_spec.loader
    llm_module = importlib.util.module_from_spec(llm_spec)
    sys.modules[llm_spec.name] = llm_module
    llm_spec.loader.exec_module(llm_module)
    return llm_module


llm_phase3 = _load_llm_phase3()


class TestStaticPatchGenerator(unittest.TestCase):
    def test_creates_patch_plan_for_approved_ec2_downsize(self) -> None:
        terraform = '''
resource "aws_instance" "api_server_01" {
  ami           = "ami-123"
  instance_type = "t3.medium"

  tags = {
    Name = "api-server-01"
  }
}

resource "aws_instance" "worker_01" {
  ami           = "ami-456"
  instance_type = "t3.medium"

  tags = {
    Name = "worker-01"
  }
}
'''.lstrip()

        plan = build_static_patch_plan(
            ec2_phase1_results=[
                {
                    "resource_id": 10,
                    "resource_name": "api-server-01",
                    "current_instance_type": "t3.medium",
                }
            ],
            ec2_phase2_results=[
                {
                    "resource_id": 10,
                    "instance_name": "api-server-01",
                    "action": "DOWNSIZE",
                    "recommended_type": "t3.small",
                }
            ],
            s3_phase1_results=[],
            tf_file_map={"main.tf": terraform},
        )

        self.assertEqual(plan.pr_title, "Apply deterministic FinOps Terraform optimization")
        self.assertEqual(len(plan.modified_files), 1)
        patched = plan.modified_files[0].new_content
        self.assertIn('resource "aws_instance" "api_server_01"', patched)
        self.assertIn('instance_type = "t3.small"', patched)
        self.assertIn('resource "aws_instance" "worker_01"', patched)
        self.assertIn('Name = "worker-01"', patched)
        self.assertEqual(patched.count('instance_type = "t3.medium"'), 1)

    def test_does_not_patch_when_phase2_status_is_blocked(self) -> None:
        plan = build_static_patch_plan(
            ec2_phase1_results=[{"resource_id": 10, "resource_name": "api-server-01"}],
            ec2_phase2_results=[
                {
                    "resource_id": 10,
                    "instance_name": "api-server-01",
                    "action": "DOWNSIZE",
                    "recommended_type": "t3.small",
                    "status": "BLOCKED",
                }
            ],
            s3_phase1_results=[],
            tf_file_map={
                "main.tf": '''
resource "aws_instance" "api_server_01" {
  instance_type = "t3.medium"
  tags = { Name = "api-server-01" }
}
'''.lstrip()
            },
        )

        self.assertEqual(plan.modified_files, [])
        self.assertTrue(any("did not approve automatic remediation" in warning for warning in plan.warnings))

    def test_does_not_patch_when_terraform_block_cannot_be_matched(self) -> None:
        plan = build_static_patch_plan(
            ec2_phase1_results=[{"resource_id": 10, "resource_name": "api-server-01"}],
            ec2_phase2_results=[
                {
                    "resource_id": 10,
                    "instance_name": "api-server-01",
                    "action": "DOWNSIZE",
                    "recommended_type": "t3.small",
                }
            ],
            s3_phase1_results=[],
            tf_file_map={
                "main.tf": '''
resource "aws_instance" "worker_01" {
  instance_type = "t3.medium"
  tags = { Name = "worker-01" }
}
'''.lstrip()
            },
        )

        self.assertEqual(plan.modified_files, [])
        self.assertTrue(any("no matching Terraform" in warning for warning in plan.warnings))

    def test_does_not_globally_replace_unrelated_instance_types(self) -> None:
        terraform = '''
module "api_server_01" {
  source        = "./modules/ec2"
  instance_type = "m5.large"
}

module "api_server_02" {
  source        = "./modules/ec2"
  instance_type = "m5.large"
}
'''.lstrip()

        plan = build_static_patch_plan(
            ec2_phase1_results=[],
            ec2_phase2_results=[
                {
                    "resource_id": 20,
                    "instance_name": "api-server-01",
                    "action": "DOWNSIZE",
                    "recommended_type": "m5.large",
                },
                {
                    "resource_id": 21,
                    "instance_name": "api-server-02",
                    "action": "DOWNSIZE",
                    "recommended_type": "m5.medium",
                },
            ],
            s3_phase1_results=[],
            tf_file_map={"main.tf": terraform},
        )

        self.assertEqual(len(plan.modified_files), 1)
        patched = plan.modified_files[0].new_content
        self.assertIn('module "api_server_01"', patched)
        self.assertIn('module "api_server_02"', patched)
        self.assertEqual(patched.count('instance_type = "m5.large"'), 1)
        self.assertEqual(patched.count('instance_type = "m5.medium"'), 1)
        self.assertTrue(any("already m5.large" in warning for warning in plan.warnings))

    def test_generates_s3_lifecycle_block_for_glacier_recommendation(self) -> None:
        terraform = '''
resource "aws_s3_bucket" "logs" {
  bucket = "my-prod-logs-bucket"
}
'''.lstrip()

        plan = build_static_patch_plan(
            ec2_phase1_results=[],
            ec2_phase2_results=[],
            s3_phase1_results=[
                {
                    "bucket_name": "my-prod-logs-bucket",
                    "action": "GLACIER_TRANSITION",
                }
            ],
            tf_file_map={"s3.tf": terraform},
        )

        self.assertEqual(len(plan.modified_files), 1)
        self.assertEqual(plan.modified_files[0].file_path, "s3.tf")
        patched = plan.modified_files[0].new_content
        self.assertIn('resource "aws_s3_bucket" "logs"', patched)
        self.assertIn(
            'resource "aws_s3_bucket_lifecycle_configuration" '
            '"finops_my_prod_logs_bucket_lifecycle"',
            patched,
        )
        self.assertIn("bucket = aws_s3_bucket.logs.id", patched)
        self.assertIn('id     = "finops-transition-cold-objects"', patched)
        self.assertIn("days          = 30", patched)
        self.assertIn('storage_class = "GLACIER"', patched)
        self.assertEqual(plan.warnings, [])

    def test_appends_s3_lifecycle_block_to_bucket_file(self) -> None:
        plan = build_static_patch_plan(
            ec2_phase1_results=[],
            ec2_phase2_results=[],
            s3_phase1_results=[
                {
                    "bucket_name": "archive-prod-001",
                    "recommended_storage_class": "STANDARD_IA",
                }
            ],
            tf_file_map={
                "buckets.tf": '''
resource "aws_s3_bucket" "archive" {
  bucket = "archive-prod-001"
}
'''.lstrip(),
                "other.tf": '''
resource "aws_s3_bucket" "unrelated" {
  bucket = "unrelated-prod-001"
}
'''.lstrip(),
            },
        )

        self.assertEqual(len(plan.modified_files), 1)
        self.assertEqual(plan.modified_files[0].file_path, "buckets.tf")
        self.assertIn('storage_class = "STANDARD_IA"', plan.modified_files[0].new_content)

    def test_does_not_patch_s3_when_lifecycle_configuration_already_exists(self) -> None:
        terraform = '''
resource "aws_s3_bucket" "logs" {
  bucket = "my-prod-logs-bucket"
}

resource "aws_s3_bucket_lifecycle_configuration" "logs_lifecycle" {
  bucket = aws_s3_bucket.logs.id
}
'''.lstrip()

        plan = build_static_patch_plan(
            ec2_phase1_results=[],
            ec2_phase2_results=[],
            s3_phase1_results=[
                {
                    "bucket_name": "my-prod-logs-bucket",
                    "action": "SET_LIFECYCLE",
                }
            ],
            tf_file_map={"s3.tf": terraform},
        )

        self.assertEqual(plan.modified_files, [])
        self.assertTrue(any("lifecycle configuration already exists" in warning for warning in plan.warnings))

    def test_does_not_patch_s3_when_bucket_match_is_ambiguous(self) -> None:
        plan = build_static_patch_plan(
            ec2_phase1_results=[],
            ec2_phase2_results=[],
            s3_phase1_results=[
                {
                    "bucket_name": "shared-logs-bucket",
                    "action": "GLACIER_TRANSITION",
                }
            ],
            tf_file_map={
                "a.tf": '''
resource "aws_s3_bucket" "logs_a" {
  bucket = "shared-logs-bucket"
}
'''.lstrip(),
                "b.tf": '''
resource "aws_s3_bucket" "logs_b" {
  bucket = "shared-logs-bucket"
}
'''.lstrip(),
            },
        )

        self.assertEqual(plan.modified_files, [])
        self.assertTrue(any("ambiguous Terraform S3 bucket match" in warning for warning in plan.warnings))

    def test_does_not_patch_s3_unsupported_storage_class(self) -> None:
        plan = build_static_patch_plan(
            ec2_phase1_results=[],
            ec2_phase2_results=[],
            s3_phase1_results=[
                {
                    "bucket_name": "my-prod-logs-bucket",
                    "action": "TRANSITION",
                    "recommended_storage_class": "EXPRESS_ONEZONE",
                }
            ],
            tf_file_map={
                "s3.tf": '''
resource "aws_s3_bucket" "logs" {
  bucket = "my-prod-logs-bucket"
}
'''.lstrip()
            },
        )

        self.assertEqual(plan.modified_files, [])
        self.assertTrue(any("unsupported S3 storage class" in warning for warning in plan.warnings))


class TestPhase3PatchSelection(unittest.TestCase):
    def assert_patch_generation_metadata_keys(self, metadata: dict) -> None:
        self.assertTrue(
            {
                "source",
                "patch_source_mode",
                "safety_requested_static",
                "llm_generated_code_ignored",
                "llm_modified_files_count",
                "selected_modified_files_count",
                "selected_warnings",
            }.issubset(metadata.keys())
        )

    def test_select_patch_plan_uses_llm_plan_when_safety_allows(self) -> None:
        llm_plan = PatchPlan(
            modified_files=[ModifiedFile("llm.tf", "llm content")],
            pr_title="LLM patch",
            pr_description="Generated by LLM.",
            warnings=["llm warning"],
        )
        output = {
            "code_generation_safety": {"use_static_patch_fallback": False},
            "runs": [{"llm": {"parsed": {"modified_files": [{"file_path": "llm.tf"}]}}}],
        }

        with patch.dict(os.environ, {"PHASE3_PATCH_SOURCE": "auto"}, clear=False):
            selected = llm_phase3._select_patch_plan(
                output=output,
                llm_patch_plan=llm_plan,
                ec2_phase1_results=[],
                ec2_phase2_results=[],
                s3_phase1_results=[],
                tf_file_map={},
            )

        self.assertIs(selected, llm_plan)
        self.assertEqual(output["patch_generation"]["source"], "llm")
        self.assertEqual(output["patch_generation"]["patch_source_mode"], "auto")
        self.assertFalse(output["patch_generation"]["safety_requested_static"])
        self.assertFalse(output["patch_generation"]["llm_generated_code_ignored"])
        self.assertEqual(output["patch_generation"]["llm_modified_files_count"], 1)
        self.assertEqual(output["patch_generation"]["selected_modified_files_count"], 1)
        self.assertEqual(output["patch_generation"]["selected_warnings"], ["llm warning"])
        self.assert_patch_generation_metadata_keys(output["patch_generation"])

    def test_select_patch_plan_uses_static_plan_when_safety_requires_fallback(self) -> None:
        llm_plan = PatchPlan(
            modified_files=[ModifiedFile("llm.tf", "unsafe llm content")],
            pr_title="LLM patch",
            pr_description="Generated by LLM.",
            warnings=[],
        )
        terraform = '''
resource "aws_instance" "api_server_01" {
  ami           = "ami-123"
  instance_type = "t3.medium"

  tags = {
    Name = "api-server-01"
  }
}
'''.lstrip()
        output = {
            "code_generation_safety": {"use_static_patch_fallback": True},
            "runs": [
                {
                    "llm": {
                        "parsed": {
                            "modified_files": [
                                {"file_path": "llm.tf", "new_content": "unsafe llm content"}
                            ]
                        }
                    }
                }
            ],
        }

        with patch.dict(os.environ, {"PHASE3_PATCH_SOURCE": "auto"}, clear=False):
            selected = llm_phase3._select_patch_plan(
                output=output,
                llm_patch_plan=llm_plan,
                ec2_phase1_results=[{"resource_id": 10, "resource_name": "api-server-01"}],
                ec2_phase2_results=[
                    {
                        "resource_id": 10,
                        "instance_name": "api-server-01",
                        "action": "DOWNSIZE",
                        "recommended_type": "t3.small",
                    }
                ],
                s3_phase1_results=[],
                tf_file_map={"main.tf": terraform},
            )

        self.assertEqual(output["patch_generation"]["source"], "static")
        self.assertEqual(output["patch_generation"]["patch_source_mode"], "auto")
        self.assertTrue(output["patch_generation"]["safety_requested_static"])
        self.assertTrue(output["patch_generation"]["llm_generated_code_ignored"])
        self.assertEqual(output["patch_generation"]["llm_modified_files_count"], 1)
        self.assertEqual(output["patch_generation"]["selected_modified_files_count"], 1)
        self.assertEqual(output["runs"][0]["llm"]["parsed"]["modified_files"][0]["file_path"], "llm.tf")
        self.assertEqual(selected.modified_files[0].file_path, "main.tf")
        self.assertIn('instance_type = "t3.small"', selected.modified_files[0].new_content)
        self.assert_patch_generation_metadata_keys(output["patch_generation"])

    def test_patch_source_static_forces_static_when_safety_allows_llm(self) -> None:
        llm_plan = PatchPlan(
            modified_files=[ModifiedFile("llm.tf", "llm content")],
            pr_title="LLM patch",
            pr_description="Generated by LLM.",
            warnings=[],
        )
        terraform = '''
resource "aws_instance" "api_server_01" {
  instance_type = "t3.medium"
  tags = { Name = "api-server-01" }
}
'''.lstrip()
        output = {"code_generation_safety": {"use_static_patch_fallback": False}, "runs": []}

        with patch.dict(os.environ, {"PHASE3_PATCH_SOURCE": "static"}, clear=False):
            selected = llm_phase3._select_patch_plan(
                output=output,
                llm_patch_plan=llm_plan,
                ec2_phase1_results=[{"resource_id": 10, "resource_name": "api-server-01"}],
                ec2_phase2_results=[
                    {
                        "resource_id": 10,
                        "instance_name": "api-server-01",
                        "action": "DOWNSIZE",
                        "recommended_type": "t3.small",
                    }
                ],
                s3_phase1_results=[],
                tf_file_map={"main.tf": terraform},
            )

        self.assertEqual(output["patch_generation"]["source"], "static")
        self.assertEqual(output["patch_generation"]["patch_source_mode"], "static")
        self.assertFalse(output["patch_generation"]["safety_requested_static"])
        self.assertTrue(output["patch_generation"]["llm_generated_code_ignored"])
        self.assertEqual(
            output["patch_generation"]["reason"],
            "PHASE3_PATCH_SOURCE=static forced deterministic static PatchPlan.",
        )
        self.assertEqual(selected.modified_files[0].file_path, "main.tf")
        self.assertIn('instance_type = "t3.small"', selected.modified_files[0].new_content)
        self.assert_patch_generation_metadata_keys(output["patch_generation"])

    def test_patch_source_llm_forces_llm_when_safety_requests_static(self) -> None:
        llm_plan = PatchPlan(
            modified_files=[ModifiedFile("llm.tf", "llm content")],
            pr_title="LLM patch",
            pr_description="Generated by LLM.",
            warnings=[],
        )
        output = {"code_generation_safety": {"use_static_patch_fallback": True}, "runs": []}

        with patch.dict(os.environ, {"PHASE3_PATCH_SOURCE": "llm"}, clear=False):
            selected = llm_phase3._select_patch_plan(
                output=output,
                llm_patch_plan=llm_plan,
                ec2_phase1_results=[],
                ec2_phase2_results=[],
                s3_phase1_results=[],
                tf_file_map={},
            )

        self.assertIs(selected, llm_plan)
        self.assertEqual(output["patch_generation"]["source"], "llm")
        self.assertEqual(output["patch_generation"]["patch_source_mode"], "llm")
        self.assertTrue(output["patch_generation"]["safety_requested_static"])
        self.assertFalse(output["patch_generation"]["llm_generated_code_ignored"])
        self.assertEqual(
            output["patch_generation"]["reason"],
            "PHASE3_PATCH_SOURCE=llm forced LLM PatchPlan.",
        )
        self.assertEqual(output["patch_generation"]["selected_warnings"], [])
        self.assert_patch_generation_metadata_keys(output["patch_generation"])

    def test_invalid_patch_source_defaults_to_auto(self) -> None:
        llm_plan = PatchPlan(
            modified_files=[ModifiedFile("llm.tf", "llm content")],
            pr_title="LLM patch",
            pr_description="Generated by LLM.",
            warnings=[],
        )
        output = {"code_generation_safety": {"use_static_patch_fallback": False}, "runs": []}

        with patch.dict(os.environ, {"PHASE3_PATCH_SOURCE": "invalid"}, clear=False):
            selected = llm_phase3._select_patch_plan(
                output=output,
                llm_patch_plan=llm_plan,
                ec2_phase1_results=[],
                ec2_phase2_results=[],
                s3_phase1_results=[],
                tf_file_map={},
            )

        self.assertIs(selected, llm_plan)
        self.assertEqual(output["patch_generation"]["source"], "llm")
        self.assertEqual(output["patch_generation"]["patch_source_mode"], "auto")
        self.assertFalse(output["patch_generation"]["safety_requested_static"])

    def test_static_selection_records_static_generator_warnings(self) -> None:
        llm_plan = PatchPlan(
            modified_files=[ModifiedFile("llm.tf", "unsafe llm content")],
            pr_title="LLM patch",
            pr_description="Generated by LLM.",
            warnings=[],
        )
        output = {"code_generation_safety": {"use_static_patch_fallback": True}, "runs": []}

        with patch.dict(os.environ, {"PHASE3_PATCH_SOURCE": "auto"}, clear=False):
            selected = llm_phase3._select_patch_plan(
                output=output,
                llm_patch_plan=llm_plan,
                ec2_phase1_results=[{"resource_id": 10, "resource_name": "api-server-01"}],
                ec2_phase2_results=[
                    {
                        "resource_id": 10,
                        "instance_name": "api-server-01",
                        "action": "DOWNSIZE",
                        "recommended_type": "t3.small",
                    }
                ],
                s3_phase1_results=[],
                tf_file_map={},
            )

        self.assertEqual(selected.modified_files, [])
        self.assertEqual(output["patch_generation"]["source"], "static")
        self.assertTrue(output["patch_generation"]["llm_generated_code_ignored"])
        self.assertEqual(output["patch_generation"]["llm_modified_files_count"], 1)
        self.assertEqual(output["patch_generation"]["selected_modified_files_count"], 0)
        self.assertTrue(
            any(
                "no matching Terraform" in warning
                for warning in output["patch_generation"]["selected_warnings"]
            )
        )
        self.assert_patch_generation_metadata_keys(output["patch_generation"])


if __name__ == "__main__":
    unittest.main()
