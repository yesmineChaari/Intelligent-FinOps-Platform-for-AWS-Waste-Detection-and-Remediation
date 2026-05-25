"""Static boundary tests for the self-contained container architecture.

This suite parses worker and shared-package imports to prevent cross-agent
business-logic dependencies, inspects Dockerfiles to ensure each image copies
only its owned application package and ``shared/``, and validates that the
root Compose definition exposes the required Redis and agent services.
"""

import ast
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _imports_forbidden(imports: set[str], forbidden: tuple[str, ...]) -> set[str]:
    return {
        name
        for name in imports
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden)
    }


class TestContainerBoundaries(unittest.TestCase):
    def test_agent1_entrypoint_does_not_import_agent2_or_phase3_logic(self) -> None:
        imports = _imports(ROOT / "agent1" / "main.py")
        forbidden = ("agent2", "phase3", "llm_benchmarking")

        self.assertEqual(_imports_forbidden(imports, forbidden), set())

    def test_agent2_entrypoint_does_not_import_deterministic_phase_logic(self) -> None:
        imports = _imports(ROOT / "agent2" / "main.py")
        forbidden = (
            "phase1.detection",
            "phase1.s3_detection",
            "phase2.guardrails",
            "agent1.phase1.detection",
            "agent1.phase1.s3_detection",
            "agent1.phase2.guardrails",
        )

        self.assertEqual(_imports_forbidden(imports, forbidden), set())

    def test_shared_package_does_not_import_agent_business_logic(self) -> None:
        forbidden = (
            "phase1",
            "phase2",
            "phase3",
            "llm_benchmarking",
            "agent1.phase1",
            "agent1.phase2",
            "agent2.phase3",
            "agent2.llm_benchmarking",
        )

        for source_file in (ROOT / "shared").rglob("*.py"):
            offending = _imports_forbidden(_imports(source_file), forbidden)
            self.assertEqual(offending, set(), f"{source_file} imports {sorted(offending)}")

    def test_dockerfiles_copy_only_worker_owned_application_packages(self) -> None:
        agent1_dockerfile = (ROOT / "agent1" / "Dockerfile").read_text(encoding="utf-8").lower()
        agent2_dockerfile = (ROOT / "agent2" / "Dockerfile").read_text(encoding="utf-8").lower()

        self.assertIn("copy agent1/", agent1_dockerfile)
        self.assertIn("copy shared/", agent1_dockerfile)
        self.assertNotIn("agent2", agent1_dockerfile)
        self.assertNotIn("phase3", agent1_dockerfile)
        self.assertNotIn("llm_benchmarking", agent1_dockerfile)

        self.assertIn("copy agent2/", agent2_dockerfile)
        self.assertIn("copy shared/", agent2_dockerfile)
        self.assertNotIn("agent1/phase1", agent2_dockerfile)
        self.assertNotIn("agent1/phase2", agent2_dockerfile)

    def test_compose_defines_required_agent_services(self) -> None:
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))

        self.assertTrue({"redis", "agent0", "agent1", "agent2"} <= set(compose["services"]))


if __name__ == "__main__":
    unittest.main()
