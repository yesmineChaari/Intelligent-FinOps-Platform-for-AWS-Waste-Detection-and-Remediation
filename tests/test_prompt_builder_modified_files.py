import importlib
import sys
import unittest
from pathlib import Path


def _load_prompt_builder():
    repo_path = Path(__file__).resolve().parents[1] / "agent2" / "llm_benchmarking" / "IaC-Evaluation-Pipeline"
    repo_str = str(repo_path)
    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)
    return importlib.import_module("prompts.prompt_builder")


class TestPromptBuilderModifiedFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.prompt_builder = _load_prompt_builder()

    def test_single_resource_schema_adds_modified_files_and_keeps_terraform_block(self) -> None:
        schema = self.prompt_builder.MODE1_2_SCHEMA

        self.assertIn('"terraform_action": "NONE | SCRIPT_HANDLES | LLM_GENERATED"', schema)
        self.assertIn('"terraform_block":', schema)
        self.assertIn('"modified_files": [', schema)
        self.assertIn('"file_path": "path/from/repo/root.tf"', schema)
        self.assertIn('"new_content": "full final content of the file after the change"', schema)
        self.assertIn('"pr_title": ""', schema)
        self.assertIn('"pr_description": ""', schema)

    def test_prompt_requires_full_file_content_and_existing_file_headers(self) -> None:
        system_prompt = self.prompt_builder.MODE1_2_SYSTEM

        self.assertIn("PR PATCH OUTPUT RULES:", system_prompt)
        self.assertIn("FULL FINAL CONTENT", system_prompt)
        self.assertIn("file_path must exactly match one of the file paths shown in ### FILE headers", system_prompt)
        self.assertIn("modified_files must be []", system_prompt)
        self.assertIn("ignore terraform_block and use modified_files only", system_prompt)

    def test_multi_instance_schema_uses_top_level_modified_files(self) -> None:
        schema = self.prompt_builder.MULTI_INSTANCE_SCHEMA
        addendum = self.prompt_builder.MULTI_INSTANCE_ADDENDUM

        self.assertIn('"terraform_block":', schema)
        self.assertEqual(schema.count('"modified_files": ['), 1)
        self.assertIn('"terraform_action": "NONE | SCRIPT_HANDLES | LLM_GENERATED"', schema)
        self.assertIn('"file_path": "main.tf"', schema)
        self.assertIn("at the top level, not inside individual instances", addendum)

    def test_multi_s3_schema_uses_top_level_modified_files(self) -> None:
        schema = self.prompt_builder.MULTI_FINDING_C_SCHEMA
        addendum = self.prompt_builder.MULTI_FINDING_C_ADDENDUM

        self.assertIn('"terraform_block":', schema)
        self.assertEqual(schema.count('"modified_files": ['), 1)
        self.assertIn('"terraform_action": "NONE | LLM_GENERATED"', schema)
        self.assertIn('"file_path": "modules/s3/main.tf"', schema)
        self.assertIn("at the top level, not inside individual findings", addendum)


if __name__ == "__main__":
    unittest.main()
