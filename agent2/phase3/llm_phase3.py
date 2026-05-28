from __future__ import annotations

import importlib
import logging
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_FALLBACK_MODEL = "llama3.3-70b"


def _filter_tf_bundle_for_ec2(tf_bundle: str, app_group: str) -> str:
    """Return a trimmed Terraform bundle: only main.tf, only app_group module blocks.

    Reduces prompt token count from ~8k to ~750 tokens for a single app group.
    """
    if not tf_bundle:
        return tf_bundle

    # Extract the main.tf section from the bundle (### FILE: main.tf ... ### FILE: next)
    main_tf_content = ""
    main_tf_path = ""
    file_pattern = re.compile(r"^### FILE: (.+)$", re.MULTILINE)
    matches = list(file_pattern.finditer(tf_bundle))
    for i, m in enumerate(matches):
        fname = m.group(1).strip()
        if fname.lower() in ("main.tf", "./main.tf"):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(tf_bundle)
            main_tf_content = tf_bundle[start:end].strip()
            main_tf_path = fname
            break

    if not main_tf_content:
        # Bundle has no main.tf — return as-is (don't break the flow)
        return tf_bundle

    # Keep only module blocks whose name starts with the app group prefix
    prefix = app_group.lower()  # e.g. "app1"
    module_pattern = re.compile(
        r'^(module\s+"(' + re.escape(prefix) + r'[^"]*)"[^{]*\{)',
        re.MULTILINE,
    )

    kept_blocks: list[str] = []
    # Also keep the locals block (defines app group tags)
    locals_match = re.search(r'^locals\s*\{', main_tf_content, re.MULTILINE)
    if locals_match:
        depth, i = 0, locals_match.start()
        while i < len(main_tf_content):
            ch = main_tf_content[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    kept_blocks.append(main_tf_content[locals_match.start():i + 1])
                    break
            i += 1

    for m in module_pattern.finditer(main_tf_content):
        brace_pos = main_tf_content.index("{", m.start())
        depth, i = 0, brace_pos
        while i < len(main_tf_content):
            ch = main_tf_content[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    kept_blocks.append(main_tf_content[m.start():i + 1])
                    break
            i += 1

    filtered_content = "\n\n".join(kept_blocks)
    return f"### FILE: {main_tf_path}\n{filtered_content}\n"

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


def _run_with_fallback(
    runner: Any,
    system_prompt: str,
    user_prompt: str,
    *,
    fallback_runner: Any,
    primary_key: str,
    ContextTooLargeError: type,
) -> tuple[dict, str]:
    """Run with primary model; fall back to llama3.3-70b on ContextTooLargeError.

    fallback_runner is shared across all calls so its rate-limit state (_last_call)
    is preserved and the interval_seconds gap is correctly enforced between fallbacks.
    """
    try:
        return runner.run(system_prompt, user_prompt), primary_key
    except ContextTooLargeError:
        if fallback_runner is None or primary_key == _FALLBACK_MODEL:
            raise
        log.warning(f"[phase3] Context too large for '{primary_key}' — retrying with '{_FALLBACK_MODEL}'")
        return fallback_runner.run(system_prompt, user_prompt), _FALLBACK_MODEL


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

    # Build the fallback runner once so its _last_call state is shared across all calls,
    # ensuring interval_seconds rate limiting is enforced between consecutive fallbacks.
    _fallback_runner = None
    if selected_model_key != _FALLBACK_MODEL:
        fallback_cfg = models.get(_FALLBACK_MODEL)
        if fallback_cfg:
            _fallback_runner = runners.get_runner(fallback_cfg, api_keys)

    _fallback_kwargs = dict(
        fallback_runner=_fallback_runner,
        primary_key=selected_model_key,
        ContextTooLargeError=runners.ContextTooLargeError,
    )

    if ec2_phase2_results:
        # Group phase2 results by app group (derived from instance_name prefix, e.g. "app1-*" → "app1")
        def _app_group(result: Any) -> str:
            for field in ("instance_name", "resource_name"):
                name = result.get(field) if isinstance(result, dict) else getattr(result, field, None)
                if name:
                    return str(name).split("-")[0]
            return "default"

        p2_by_group: dict[str, list] = defaultdict(list)
        for p2 in ec2_phase2_results:
            p2_by_group[_app_group(p2)].append(p2)

        # Index phase1 results by resource_id for fast lookup
        p1_by_rid: dict[int, Any] = {}
        for p1 in ec2_phase1_results:
            rid = p1.get("resource_id") if isinstance(p1, dict) else getattr(p1, "resource_id", None)
            if rid is not None:
                try:
                    p1_by_rid[int(rid)] = p1
                except (TypeError, ValueError):
                    pass

        for app_group, p2_list in sorted(p2_by_group.items()):
            rids = set()
            for p2 in p2_list:
                rid = p2.get("resource_id") if isinstance(p2, dict) else getattr(p2, "resource_id", None)
                if rid is not None:
                    try:
                        rids.add(int(rid))
                    except (TypeError, ValueError):
                        pass
            p1_list = [p1_by_rid[rid] for rid in rids if rid in p1_by_rid]

            ec2_tf = _filter_tf_bundle_for_ec2(tf_prompt_bundle, app_group)
            ec2_scenario = build_ec2_scenario(
                p1_list,
                p2_list,
                scenario_id=f"A_{app_group}",
                app_group=app_group.upper(),
                current_terraform=ec2_tf,
            )
            system_prompt, user_prompt = prompt_builder.build_prompt(ec2_scenario)
            llm_result, model_used = _run_with_fallback(runner, system_prompt, user_prompt, **_fallback_kwargs)
            output["runs"].append(
                {
                    "scenario_type": "ec2",
                    "app_group": app_group,
                    "model_used": model_used,
                    "scenario": ec2_scenario,
                    "llm": llm_result,
                }
            )

    for s3_result in s3_phase1_results:
        bucket_name = (
            s3_result.get("bucket_name") if isinstance(s3_result, dict)
            else getattr(s3_result, "bucket_name", "unknown")
        )
        s3_scenario = build_s3_scenario(
            [s3_result],
            scenario_id=f"C_{bucket_name}",
            current_terraform=tf_prompt_bundle,
        )
        system_prompt, user_prompt = prompt_builder.build_prompt(s3_scenario)
        llm_result, model_used = _run_with_fallback(runner, system_prompt, user_prompt, **_fallback_kwargs)
        output["runs"].append(
            {
                "scenario_type": "s3",
                "bucket_name": bucket_name,
                "model_used": model_used,
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
