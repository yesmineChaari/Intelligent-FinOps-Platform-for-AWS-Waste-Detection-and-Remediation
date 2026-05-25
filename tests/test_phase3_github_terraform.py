import os
import unittest
from unittest.mock import patch

from phase3.github_terraform import (
    TerraformSource,
    build_prompt_bundle,
    parse_github_repo_url,
    redact_terraform_secrets,
    resolve_terraform_bundle,
    should_include_tf_path,
)


class TestGitHubTerraformPaths(unittest.TestCase):
    def test_parse_github_repo_url_supports_https_without_git_suffix(self) -> None:
        self.assertEqual(
            parse_github_repo_url("https://github.com/Nour-Ben-Hadid/finops-infra"),
            ("Nour-Ben-Hadid", "finops-infra"),
        )

    def test_parse_github_repo_url_supports_https_with_git_suffix(self) -> None:
        self.assertEqual(
            parse_github_repo_url("https://github.com/Nour-Ben-Hadid/finops-infra.git"),
            ("Nour-Ben-Hadid", "finops-infra"),
        )

    def test_parse_github_repo_url_supports_ssh(self) -> None:
        self.assertEqual(
            parse_github_repo_url("git@github.com:Nour-Ben-Hadid/finops-infra.git"),
            ("Nour-Ben-Hadid", "finops-infra"),
        )

    def test_should_include_tf_path_includes_terraform_files(self) -> None:
        for path in ("main.tf", "providers.tf", "outputs.tf", "modules/ec2/main.tf", "modules/s3/variables.tf"):
            with self.subTest(path=path):
                self.assertTrue(should_include_tf_path(path))

    def test_should_include_tf_path_excludes_state_and_unsafe_directories(self) -> None:
        for path in (
            "terraform.tfstate",
            "env/prod.tfstate",
            "env/prod.tfstate.backup",
            ".terraform/modules/generated/main.tf",
            ".git/modules/main.tf",
            "node_modules/provider/main.tf",
            "__pycache__/main.tf",
            "terraform.tfvars",
        ):
            with self.subTest(path=path):
                self.assertFalse(should_include_tf_path(path))

    def test_should_include_tf_path_respects_subdir(self) -> None:
        self.assertTrue(should_include_tf_path("terraform/prod/main.tf", "terraform/prod"))
        self.assertFalse(should_include_tf_path("terraform/staging/main.tf", "terraform/prod"))
        self.assertFalse(should_include_tf_path("terraform/prod-other/main.tf", "terraform/prod"))


class TestGitHubTerraformContent(unittest.TestCase):
    def test_redact_terraform_secrets_redacts_sensitive_assignments(self) -> None:
        content = (
            'access_key = "AKIA123"\n'
            'secret_key = "secret"\n'
            'token = var.token\n'
            'password = "pass" # keep reason\n'
            'bucket = "public-name"\n'
        )

        redacted = redact_terraform_secrets(content)

        self.assertIn('access_key = "***REDACTED***"', redacted)
        self.assertIn('secret_key = "***REDACTED***"', redacted)
        self.assertIn('token = "***REDACTED***"', redacted)
        self.assertIn('password = "***REDACTED***" # keep reason', redacted)
        self.assertIn('bucket = "public-name"', redacted)
        self.assertNotIn("AKIA123", redacted)
        self.assertNotIn('"secret"', redacted)

    def test_redact_terraform_secrets_removes_sensitive_heredoc_body(self) -> None:
        content = (
            "private_key = <<-EOF\n"
            "-----BEGIN PRIVATE KEY-----\n"
            "private-material\n"
            "-----END PRIVATE KEY-----\n"
            "EOF\n"
            'name = "retained"\n'
        )

        redacted = redact_terraform_secrets(content)

        self.assertIn('private_key = "***REDACTED***"', redacted)
        self.assertNotIn("private-material", redacted)
        self.assertNotIn("BEGIN PRIVATE KEY", redacted)
        self.assertIn('name = "retained"', redacted)

    def test_build_prompt_bundle_has_sorted_file_headers(self) -> None:
        bundle = build_prompt_bundle(
            {
                "modules/ec2/main.tf": 'resource "aws_instance" "app" {}\n',
                "main.tf": 'terraform {}\n',
            }
        )

        self.assertIn("### FILE: main.tf\n```hcl\nterraform {}\n```", bundle)
        self.assertIn("### FILE: modules/ec2/main.tf", bundle)
        self.assertLess(bundle.index("### FILE: main.tf"), bundle.index("### FILE: modules/ec2/main.tf"))

    @patch("phase3.github_terraform.fetch_file_content")
    @patch("phase3.github_terraform.list_repo_files")
    def test_resolve_bundle_filters_and_redacts_fetched_files(self, list_files, fetch_file) -> None:
        list_files.return_value = [
            {"type": "blob", "path": ".terraform/modules/cache/main.tf"},
            {"type": "blob", "path": "terraform.tfstate"},
            {"type": "blob", "path": "modules/ec2/main.tf"},
            {"type": "blob", "path": "main.tf"},
        ]
        fetch_file.side_effect = lambda owner, repo, path, ref: (
            'token = "abc"\n' if path == "main.tf" else 'resource "aws_instance" "app" {}\n'
        )

        with patch.dict(os.environ, {"PHASE3_TERRAFORM_MAX_BYTES": "500000"}, clear=False):
            result = resolve_terraform_bundle(
                TerraformSource("https://github.com/Nour-Ben-Hadid/finops-infra.git")
            )

        self.assertEqual(result.owner, "Nour-Ben-Hadid")
        self.assertEqual(result.repo, "finops-infra")
        self.assertEqual(sorted(result.files), ["main.tf", "modules/ec2/main.tf"])
        self.assertIn('token = "***REDACTED***"', result.files["main.tf"])
        self.assertNotIn("terraform.tfstate", result.prompt_bundle)
        self.assertEqual(fetch_file.call_count, 2)


if __name__ == "__main__":
    unittest.main()
