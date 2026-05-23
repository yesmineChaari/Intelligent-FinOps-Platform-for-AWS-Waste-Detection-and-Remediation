import importlib
import json
import sys
import unittest
from pathlib import Path


class TestPromptBuilderTierASmoke(unittest.TestCase):
    def test_tier_a_a1_build_prompt(self) -> None:
        repo_path = Path(__file__).resolve().parents[1] / "llm_benchmarking" / "IaC-Evaluation-Pipeline"
        scenario_file = repo_path / "scenarios" / "tier_a.json"
        if not scenario_file.exists():
            self.skipTest("tier_a.json not present in workspace")

        repo_str = str(repo_path)
        if repo_str not in sys.path:
            sys.path.insert(0, repo_str)

        prompt_builder = importlib.import_module("prompts.prompt_builder")

        data = json.loads(scenario_file.read_text(encoding="utf-8"))
        scenario = data["tier_a"]["scenarios"]["A1"]

        system_prompt, user_prompt = prompt_builder.build_prompt(scenario)
        self.assertTrue(system_prompt)
        self.assertTrue(user_prompt)
        self.assertIn("Respond with ONLY valid JSON", system_prompt)


if __name__ == "__main__":
    unittest.main()
