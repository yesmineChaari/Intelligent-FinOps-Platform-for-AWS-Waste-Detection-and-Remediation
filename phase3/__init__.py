"""Phase 3 — LLM evaluation integration.

This package converts Phase1/Phase2 outputs into the scenario format used by
`llm_benchmarking/IaC-Evaluation-Pipeline` and runs the selected LLM runner.
"""

from .converter import build_ec2_scenario, build_s3_scenario
from .llm_phase3 import run_phase3_llm

__all__ = [
    "build_ec2_scenario",
    "build_s3_scenario",
    "run_phase3_llm",
]
