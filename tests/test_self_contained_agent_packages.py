import ast
import importlib
import unittest
from pathlib import Path


class TestSelfContainedAgentPackages(unittest.TestCase):
    def test_phase_imports_resolve_through_new_and_legacy_packages(self) -> None:
        preferred_loader = importlib.import_module("agent1.phase1.loader")
        legacy_loader = importlib.import_module("phase1.loader")
        preferred_detection = importlib.import_module("agent1.phase1.detection")
        legacy_detection = importlib.import_module("phase1.detection")
        preferred_phase2 = importlib.import_module("agent1.phase2")
        legacy_phase2 = importlib.import_module("phase2")
        preferred_phase3 = importlib.import_module("agent2.phase3.llm_phase3")
        legacy_phase3 = importlib.import_module("phase3.llm_phase3")

        self.assertIs(legacy_loader, preferred_loader)
        self.assertIs(legacy_detection, preferred_detection)
        self.assertIs(legacy_phase2.run_phase2, preferred_phase2.run_phase2)
        self.assertIs(legacy_phase3, preferred_phase3)

    def test_agent_owned_benchmark_package_and_legacy_alias_import(self) -> None:
        benchmark_dir = (
            Path(__file__).resolve().parents[1]
            / "agent2"
            / "llm_benchmarking"
            / "IaC-Evaluation-Pipeline"
        )
        preferred = importlib.import_module("agent2.llm_benchmarking")
        legacy = importlib.import_module("llm_benchmarking")

        self.assertTrue((benchmark_dir / "pipeline.py").exists())
        self.assertIs(legacy, preferred)

    def test_worker_sources_prefer_agent_local_phase_imports(self) -> None:
        agent1_imports = self._imports("agent1/main.py")
        agent2_imports = self._imports("agent2/main.py")

        self.assertIn("agent1.phase1.loader", agent1_imports)
        self.assertIn("agent1.phase1.detection", agent1_imports)
        self.assertIn("agent1.phase1.s3_detection", agent1_imports)
        self.assertIn("agent1.phase2", agent1_imports)
        self.assertIn("agent2.phase3.llm_phase3", agent2_imports)

    def test_legacy_main_imports_with_compatibility_packages(self) -> None:
        main = importlib.import_module("main")

        self.assertTrue(callable(main.main))

    def test_shared_source_has_no_phase_or_agent_imports(self) -> None:
        shared_dir = Path(__file__).resolve().parents[1] / "shared"
        forbidden_prefixes = (
            "agent1",
            "agent2",
            "phase1",
            "phase2",
            "phase3",
            "llm_benchmarking",
        )

        for source_file in shared_dir.rglob("*.py"):
            for imported_name in self._imports(source_file):
                self.assertFalse(
                    any(
                        imported_name == prefix or imported_name.startswith(f"{prefix}.")
                        for prefix in forbidden_prefixes
                    ),
                    f"{source_file} imports {imported_name}",
                )

    @staticmethod
    def _imports(relative_path: str | Path) -> list[str]:
        path = Path(relative_path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        return imports


if __name__ == "__main__":
    unittest.main()
