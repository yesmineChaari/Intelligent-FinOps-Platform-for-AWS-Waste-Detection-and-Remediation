import os
import unittest
from unittest.mock import patch

from main import (
    _build_terraform_source,
    _redact_current_terraform_for_logging,
    _redact_phase3_output_for_logging,
    wait_for_trigger,
)


class _FakeRedis:
    async def xread(self, *_args, **_kwargs):
        return [
            (
                b"ingestion_stream",
                [
                    (
                        b"1-0",
                        {
                            b"event": b"ingestion_complete",
                            b"terraform_repo_url": b"https://github.com/owner/infrastructure.git",
                            b"terraform_ref": b"feature/test",
                            b"terraform_subdir": b"terraform/prod",
                        },
                    )
                ],
            )
        ]


class TestMainTerraformMetadata(unittest.IsolatedAsyncioTestCase):
    async def test_wait_for_trigger_returns_decoded_redis_payload(self) -> None:
        payload = await wait_for_trigger(_FakeRedis())

        self.assertEqual(payload["event"], "ingestion_complete")
        self.assertEqual(payload["terraform_repo_url"], "https://github.com/owner/infrastructure.git")
        self.assertEqual(payload["terraform_ref"], "feature/test")
        self.assertEqual(payload["terraform_subdir"], "terraform/prod")

    def test_terraform_source_prefers_terraform_payload_fields(self) -> None:
        payload = {
            "terraform_repo_url": "https://github.com/owner/terraform.git",
            "terraform_ref": "production",
            "terraform_subdir": "tf/prod",
            "repo_url": "https://github.com/ignored/repo.git",
            "repo_ref": "ignored",
            "repo_subdir": "ignored",
        }
        with patch.dict(os.environ, {}, clear=True):
            source = _build_terraform_source(payload)

        self.assertEqual(
            source,
            {
                "repo_url": "https://github.com/owner/terraform.git",
                "ref": "production",
                "subdir": "tf/prod",
            },
        )

    def test_terraform_source_uses_legacy_payload_fields(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            source = _build_terraform_source(
                {
                    "repo_url": "https://github.com/owner/legacy.git",
                    "repo_ref": "legacy-ref",
                    "repo_subdir": "legacy/path",
                }
            )

        self.assertEqual(source["repo_url"], "https://github.com/owner/legacy.git")
        self.assertEqual(source["ref"], "legacy-ref")
        self.assertEqual(source["subdir"], "legacy/path")

    def test_empty_trigger_payload_uses_environment_fallbacks_for_skip_mode(self) -> None:
        env = {
            "PHASE3_TERRAFORM_REPO_URL": "https://github.com/owner/from-env.git",
            "PHASE3_TERRAFORM_REF": "env-ref",
            "PHASE3_TERRAFORM_SUBDIR": "env/path",
        }
        with patch.dict(os.environ, env, clear=True):
            source = _build_terraform_source({})

        self.assertEqual(source["repo_url"], env["PHASE3_TERRAFORM_REPO_URL"])
        self.assertEqual(source["ref"], "env-ref")
        self.assertEqual(source["subdir"], "env/path")

    def test_empty_trigger_payload_has_safe_defaults_without_environment(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            source = _build_terraform_source({})

        self.assertIsNone(source["repo_url"])
        self.assertEqual(source["ref"], "main")
        self.assertEqual(source["subdir"], "")

    def test_terraform_content_is_redacted_in_console_views(self) -> None:
        scenario = {
            "current_terraform": "resource {}",
            "findings": [{"current_terraform": "nested terraform"}],
        }
        output = {"runs": [{"scenario": scenario}], "terraform_source": {"files": ["main.tf"]}}

        redacted_scenario = _redact_current_terraform_for_logging(scenario)
        redacted_output = _redact_phase3_output_for_logging(output)

        self.assertEqual(redacted_scenario["current_terraform"], "<redacted 11 chars>")
        self.assertEqual(redacted_scenario["findings"][0]["current_terraform"], "<redacted 16 chars>")
        self.assertEqual(redacted_output["runs"][0]["scenario"]["current_terraform"], "<redacted 11 chars>")
        self.assertEqual(redacted_output["terraform_source"]["files"], ["main.tf"])
        self.assertEqual(scenario["current_terraform"], "resource {}")


if __name__ == "__main__":
    unittest.main()
