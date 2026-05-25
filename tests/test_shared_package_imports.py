"""Tests for the shared package API and root persistence compatibility layer.

The suite verifies that shared modules import, environment flag and string
helpers behave as configured, Redis field/payload helpers convert values
correctly, and both ``persistence`` and ``shared.persistence`` expose the same
public run/output/status functions.
"""

import importlib
import os
import unittest
from unittest.mock import patch

import persistence
import shared.persistence as shared_persistence
from shared.events import build_deterministic_complete_payload, decode_stream_fields
from shared.settings import env_flag, env_str


PERSISTENCE_SYMBOLS = (
    "start_optimization_run",
    "save_phase1_outputs",
    "save_phase2_outputs",
    "save_phase3_outputs",
    "complete_optimization_run",
    "update_optimization_run_status",
)


class TestSharedPackageImports(unittest.TestCase):
    def test_shared_imports_successfully(self) -> None:
        modules = [
            importlib.import_module(module_name)
            for module_name in (
                "shared",
                "shared.contracts",
                "shared.db",
                "shared.events",
                "shared.settings",
            )
        ]

        self.assertEqual(modules[0].__name__, "shared")

    def test_env_flag_handles_true_false_and_default_values(self) -> None:
        with patch.dict(os.environ, {"ENABLED": "TrUe", "DISABLED": "off"}, clear=True):
            self.assertTrue(env_flag("ENABLED"))
            self.assertFalse(env_flag("DISABLED", default=True))
            self.assertTrue(env_flag("MISSING", default=True))
            self.assertFalse(env_flag("ALSO_MISSING"))

    def test_env_str_returns_environment_value_or_default(self) -> None:
        with patch.dict(os.environ, {"REGION": "us-east-1"}, clear=True):
            self.assertEqual(env_str("REGION"), "us-east-1")
            self.assertEqual(env_str("MISSING", "fallback"), "fallback")
            self.assertIsNone(env_str("ALSO_MISSING"))

    def test_decode_stream_fields_handles_bytes_and_strings(self) -> None:
        fields = {b"event": b"ingestion_complete", "workspace_key": "aws-prod"}

        self.assertEqual(
            decode_stream_fields(fields),
            {"event": "ingestion_complete", "workspace_key": "aws-prod"},
        )

    def test_build_deterministic_complete_payload_converts_and_omits_values(self) -> None:
        payload = build_deterministic_complete_payload(
            123,
            workspace_key="aws-prod",
            terraform_ref=None,
        )

        self.assertEqual(payload, {"run_id": "123", "workspace_key": "aws-prod"})

    def test_root_and_shared_persistence_expose_the_same_symbols(self) -> None:
        self.assertEqual(persistence.__all__, shared_persistence.__all__)
        for symbol in PERSISTENCE_SYMBOLS:
            self.assertTrue(hasattr(persistence, symbol))
            self.assertTrue(hasattr(shared_persistence, symbol))
            self.assertIs(getattr(persistence, symbol), getattr(shared_persistence, symbol))


if __name__ == "__main__":
    unittest.main()
