from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any

from .converter import build_ec2_scenario, build_s3_scenario
from .github_pr import create_pull_request_from_patch_plan
from .github_terraform import TerraformSource, resolve_terraform_bundle
from .patch_schema import extract_patch_plan


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
    terraform_source: dict[str, Any] | None = None,
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

    source_config = terraform_source or {}
    repo_url = source_config.get("repo_url") or os.environ.get("PHASE3_TERRAFORM_REPO_URL")
    repo_ref = source_config.get("ref") or os.environ.get("PHASE3_TERRAFORM_REF") or "main"
    repo_subdir = source_config.get("subdir") or os.environ.get("PHASE3_TERRAFORM_SUBDIR") or ""
    tf_prompt_bundle = ""
    tf_file_map: dict[str, str] = {}
    tf_warnings: list[str] = []

    if repo_url:
        try:
            tf_bundle = resolve_terraform_bundle(
                TerraformSource(repo_url=repo_url, ref=repo_ref, subdir=repo_subdir)
            )
            tf_prompt_bundle = tf_bundle.prompt_bundle
            tf_file_map = tf_bundle.files
            tf_warnings = list(tf_bundle.warnings)
        except Exception as exc:
            tf_warnings.append(f"Failed to resolve Terraform bundle: {exc}")

    output: dict[str, Any] = {
        "model": {
            "key": selected_model_key,
            "provider": model_cfg.get("provider"),
            "model_id": model_cfg.get("model_id"),
        },
        "terraform_source": {
            "repo_url": repo_url,
            "ref": repo_ref,
            "subdir": repo_subdir,
            "file_count": len(tf_file_map),
            "files": sorted(tf_file_map.keys()),
            "warnings": tf_warnings,
        },
        "runs": [],
    }

    if ec2_phase2_results:
        ec2_scenario = build_ec2_scenario(
            ec2_phase1_results,
            ec2_phase2_results,
            current_terraform=tf_prompt_bundle,
        )
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
        s3_scenario = build_s3_scenario(
            list(s3_phase1_results),
            current_terraform=tf_prompt_bundle,
        )
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

    patch_plan = extract_patch_plan(output)
    output["patch_plan"] = {
        "modified_files": [
            {
                "file_path": modified_file.file_path,
                "new_content_length": len(modified_file.new_content),
            }
            for modified_file in patch_plan.modified_files
        ],
        "pr_title": patch_plan.pr_title,
        "pr_description": patch_plan.pr_description,
        "warnings": patch_plan.warnings,
    }

    create_pr = os.environ.get("PHASE3_CREATE_PR", "0").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if not patch_plan.modified_files:
        output["pull_request"] = {
            "created": False,
            "reason": "No modified files were returned by the LLM.",
        }
    elif not create_pr or not repo_url:
        output["pull_request"] = {
            "created": False,
            "reason": "PHASE3_CREATE_PR is disabled or repo_url is missing.",
        }
    else:
        try:
            pr_result = create_pull_request_from_patch_plan(
                TerraformSource(repo_url=repo_url, ref=repo_ref, subdir=repo_subdir),
                patch_plan,
                tf_file_map,
            )
            output["pull_request"] = {
                "created": pr_result.created,
                "branch_name": pr_result.branch_name,
                "pr_url": pr_result.pr_url,
                "changed_files": pr_result.changed_files,
                "warnings": pr_result.warnings,
                "errors": pr_result.errors,
            }
        except Exception as exc:
            output["pull_request"] = {
                "created": False,
                "branch_name": None,
                "pr_url": None,
                "changed_files": [],
                "warnings": [],
                "errors": [str(exc)],
            }

    return output
