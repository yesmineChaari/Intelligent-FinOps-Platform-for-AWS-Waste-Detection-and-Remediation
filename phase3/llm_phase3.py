from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any

from .converter import build_ec2_scenario, build_s3_scenario


def _iac_eval_repo_path() -> Path:
    """Path to the embedded IaC-Evaluation-Pipeline repo (vendored under llm_benchmarking/)."""
    return Path(__file__).resolve().parents[1] / "llm_benchmarking" / "IaC-Evaluation-Pipeline"


def _import_iac_eval(repo_path: Path):
    if not repo_path.exists():
        raise FileNotFoundError(
            f"IaC-Evaluation-Pipeline not found at '{repo_path}'. "
            "Expected it under 'llm_benchmarking/IaC-Evaluation-Pipeline'."
        )

    repo_str = str(repo_path)
    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)

    config = importlib.import_module("config")
    prompt_builder = importlib.import_module("prompts.prompt_builder")
    runners = importlib.import_module("runners")
    return config, prompt_builder, runners


def run_phase3_llm(
    ec2_phase1_results: list[Any],
    ec2_phase2_results: list[Any],
    s3_phase1_results: list[Any],
    model_key: str | None = None,
) -> dict[str, Any]:
    """Run Phase 3 LLM evaluation.

    Returns a JSON-serializable dict containing:
      - the scenario(s) built from Phase1/Phase2 output
      - the parsed LLM JSON response (or parse_error)

    This function is synchronous; call it via asyncio.to_thread() from async code.
    """

    repo_path = _iac_eval_repo_path()
    try:
        config, prompt_builder, runners = _import_iac_eval(repo_path)
    except Exception as exc:
        return {
            "error": f"Phase3 import failed: {exc}",
            "iac_eval_repo_path": str(repo_path),
        }

    models: dict[str, dict] = getattr(config, "MODELS", {})
    if not models:
        return {
            "error": "Phase3 config has no MODELS.",
            "iac_eval_repo_path": str(repo_path),
        }

    selected_model_key = (
        model_key
        or os.environ.get("PHASE3_MODEL")
        or next(iter(models.keys()))
    )

    if selected_model_key not in models:
        return {
            "error": f"Unknown PHASE3_MODEL '{selected_model_key}'.",
            "available_models": sorted(models.keys()),
        }

    model_cfg = models[selected_model_key]
    api_keys: dict[str, str] = {
        "groq": os.environ.get("GROQ_API_KEY", ""),
        "google": os.environ.get("GOOGLE_API_KEY", ""),
        "mistral": os.environ.get("MISTRAL_API_KEY", ""),
    }
    runner = runners.get_runner(model_cfg, api_keys)

    output: dict[str, Any] = {
        "model": {
            "key": selected_model_key,
            "provider": model_cfg.get("provider"),
            "model_id": model_cfg.get("model_id"),
        },
        "runs": [],
    }

    if ec2_phase2_results:
        ec2_scenario = build_ec2_scenario(ec2_phase1_results, ec2_phase2_results)
        system_prompt, user_prompt = prompt_builder.build_prompt(ec2_scenario)
        llm_result = runner.run(system_prompt, user_prompt)
        output["runs"].append(
            {
                "scenario_type": "ec2",
                "scenario": ec2_scenario,
                "llm": llm_result,
            }
        )

    if s3_phase1_results:
        s3_scenario = build_s3_scenario(list(s3_phase1_results))
        system_prompt, user_prompt = prompt_builder.build_prompt(s3_scenario)
        llm_result = runner.run(system_prompt, user_prompt)
        output["runs"].append(
            {
                "scenario_type": "s3",
                "scenario": s3_scenario,
                "llm": llm_result,
            }
        )

    if not output["runs"]:
        output["note"] = "No EC2 Phase2 results or S3 findings to evaluate."

    return output
