from __future__ import annotations

import importlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from .converter import build_ec2_scenario, build_s3_scenario
from .ec2_instance_patch import (
    apply_ec2_instance_type_updates,
    parsed_decision_action,
    scoped_terraform_for_instance,
)
from .github_pr import create_pull_request_from_patch_plan
from .github_terraform import TerraformSource, resolve_terraform_bundle
from .local_patch import validate_patch_plan
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


def _read(obj: Any, field: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(field, default)
    return getattr(obj, field, default)


def _env_enabled(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes"}


def _resource_key(obj: Any) -> str | None:
    for field in ("resource_id", "instance_name", "resource_name", "instance_id"):
        value = _read(obj, field)
        if value is not None:
            return str(value)
    return None


def _phase2_action(phase2_result: Any) -> str:
    action = _read(phase2_result, "phase2_action") or _read(phase2_result, "action")
    action = getattr(action, "value", action)
    return str(action or "").upper()


def _patchable_ec2_phase2(phase2_result: Any) -> bool:
    return (
        _phase2_action(phase2_result) == "DOWNSIZE"
        and bool(_read(phase2_result, "instance_type") or _read(phase2_result, "current_instance_type"))
        and bool(_read(phase2_result, "recommended_type"))
    )


def _synthetic_ec2_llm_result(
    scenario: dict[str, Any],
    phase2_result: Any,
    reason: str,
    *,
    verdict: str | None = None,
) -> dict[str, Any]:
    resource = _scenario_instance(scenario) or {}
    action = _phase2_action(phase2_result) or resource.get("agent2_decision", {}).get("action") or "KEEP"
    return {
        "parsed": {
            "verdict": verdict or ("OPTIMAL" if action == "DOWNSIZE" else "NOT_EVALUATED"),
            "decision_summary": {
                "action": action,
                "decided_by": "AGENT_DETERMINISTIC",
                "rationale": reason,
            },
            "technical_explanation": reason,
            "terraform_action": "NONE",
        }
    }


def _compact_ec2_validation_prompts(scenario: dict[str, Any]) -> tuple[str, str]:
    resource = _scenario_instance(scenario) or {}
    decision = resource.get("agent2_decision") if isinstance(resource.get("agent2_decision"), dict) else {}
    cost = resource.get("cost") if isinstance(resource.get("cost"), dict) else {}
    payload = {
        "instance_id": resource.get("instance_id"),
        "instance_name": resource.get("instance_name"),
        "current_instance_type": resource.get("instance_type"),
        "role": resource.get("role"),
        "agent2_decision": {
            "action": decision.get("action"),
            "waste_type": decision.get("waste_type"),
            "detection_reason": decision.get("detection_reason"),
            "recommended_type": decision.get("recommended_type"),
            "blast_radius": decision.get("blast_radius"),
            "p95_cpu": decision.get("p95_cpu"),
            "p99_cpu": decision.get("p99_cpu"),
            "max_cpu": decision.get("max_cpu"),
            "p95_ram": decision.get("p95_ram"),
            "cv": decision.get("cv"),
        },
        "cost": {
            "current_cost_per_hour": cost.get("current_cost_per_hour"),
            "recommended_cost_per_hour": cost.get("recommended_cost_per_hour"),
            "waste_per_month": cost.get("waste_per_month"),
        },
        "terraform_module": scenario.get("current_terraform") or "",
    }
    system_prompt = (
        "You are an AWS FinOps reviewer. Validate one EC2 downsizing recommendation. "
        "Return ONLY valid compact JSON. Do not return Terraform or markdown."
    )
    user_prompt = (
        "Decide if the recommendation is safe to apply as an instance_type-only Terraform change.\n"
        "Rules:\n"
        "- If the action is not DOWNSIZE, return action KEEP.\n"
        "- If recommended_type is missing, same as current, or not visible in the Terraform module, return action KEEP.\n"
        "- If blast_radius is greater than 3, return action KEEP.\n"
        "- If safe, return action DOWNSIZE and new_instance_type exactly equal to the target instance type.\n"
        "- Never propose any Terraform change except instance_type.\n\n"
        "JSON schema:\n"
        "{\"verdict\":\"OPTIMAL|SUBOPTIMAL|INCORRECT\","
        "\"decision_summary\":{\"action\":\"DOWNSIZE|KEEP\","
        "\"decided_by\":\"AGENT_VALIDATED|LLM_OVERRIDDEN\","
        "\"rationale\":\"short reason\"},"
        "\"new_instance_type\":\"string or null\","
        "\"technical_explanation\":\"short explanation\","
        "\"terraform_action\":\"SCRIPT_HANDLES|NONE\"}\n\n"
        "Input:\n"
        f"{json.dumps(payload, separators=(',', ':'), default=str)}"
    )
    return system_prompt, user_prompt


def _normalize_compact_ec2_result(llm_result: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    parsed = llm_result.get("parsed")
    if not isinstance(parsed, dict):
        return llm_result
    parsed.pop("modified_files", None)

    decision = parsed.get("decision_summary")
    if not isinstance(decision, dict):
        decision = {}
        parsed["decision_summary"] = decision

    action = str(decision.get("action") or "").upper()
    if action != "DOWNSIZE":
        decision["action"] = "KEEP"
        parsed["new_instance_type"] = None
        parsed["terraform_action"] = "NONE"
        return llm_result

    resource = _scenario_instance(scenario) or {}
    agent2_decision = resource.get("agent2_decision") if isinstance(resource.get("agent2_decision"), dict) else {}
    target_type = (
        parsed.get("new_instance_type")
        or parsed.get("recommended_type")
        or parsed.get("recommended_instance_type")
    )
    if not target_type and isinstance(parsed.get("terraform_block"), str):
        match = re.search(r'(?m)^[ \t]*instance_type\s*=\s*"([^"]+)"', parsed["terraform_block"])
        if match:
            target_type = match.group(1)
    target_type = target_type or agent2_decision.get("recommended_type")
    target_type = str(target_type).strip() if target_type else ""
    current_type = str(resource.get("instance_type") or "").strip()
    if not target_type or target_type == current_type:
        decision["action"] = "KEEP"
        parsed["new_instance_type"] = None
        parsed["terraform_action"] = "NONE"
    else:
        parsed["new_instance_type"] = target_type
        parsed["recommended_type"] = target_type
        parsed["terraform_action"] = "SCRIPT_HANDLES"
        parsed.setdefault("verdict", "OPTIMAL")
        decision.setdefault("decided_by", "AGENT_VALIDATED")
        decision.setdefault("rationale", "Validated as a safe instance_type-only downsizing change.")
    return llm_result


def _phase1_by_resource_key(phase1_results: list[Any]) -> dict[str, Any]:
    by_key: dict[str, Any] = {}
    for result in phase1_results:
        for field in ("resource_id", "resource_name", "instance_name", "instance_id"):
            value = _read(result, field)
            if value is not None:
                by_key[str(value)] = result
    return by_key


def _single_ec2_scenario(
    phase1_by_key: dict[str, Any],
    phase2_result: Any,
    *,
    current_terraform: str,
) -> dict[str, Any]:
    phase1_matches: list[Any] = []
    for field in ("resource_id", "instance_name", "resource_name", "instance_id"):
        value = _read(phase2_result, field)
        if value is None:
            continue
        match = phase1_by_key.get(str(value))
        if match is not None and match not in phase1_matches:
            phase1_matches.append(match)

    key = _resource_key(phase2_result) or "unknown"
    return build_ec2_scenario(
        phase1_matches,
        [phase2_result],
        scenario_id=f"A_auto_{key}",
        description="Auto-generated EC2 scenario from Phase1/Phase2 outputs",
        current_terraform=current_terraform,
    )


def _scenario_instance(scenario: dict[str, Any]) -> dict[str, Any] | None:
    resources = scenario.get("flagged_resources")
    if isinstance(resources, list) and resources:
        first = resources[0]
        return first if isinstance(first, dict) else None
    return None


def _strip_ec2_generated_files(llm_result: dict[str, Any]) -> dict[str, Any]:
    """Ignore EC2 file rewrites; code applies validated instance_type edits."""

    parsed = llm_result.get("parsed")
    if not isinstance(parsed, dict):
        return llm_result

    parsed.pop("modified_files", None)
    instances = parsed.get("instances")
    if isinstance(instances, dict):
        for child in instances.values():
            if isinstance(child, dict):
                child.pop("modified_files", None)
    return llm_result


def _ec2_update_from_run(run: dict[str, Any]) -> tuple[str, str] | None:
    scenario = run.get("scenario")
    llm = run.get("llm")
    if not isinstance(scenario, dict) or not isinstance(llm, dict):
        return None

    parsed = llm.get("parsed")
    if not isinstance(parsed, dict):
        return None

    resource = _scenario_instance(scenario)
    if not resource:
        return None

    instance_id = resource.get("instance_id")
    if not instance_id:
        return None

    action = parsed_decision_action(parsed, str(instance_id))
    if str(action).upper() != "DOWNSIZE":
        return None

    agent2_decision = resource.get("agent2_decision")
    current_type = resource.get("instance_type")
    llm_type = _llm_instance_type(parsed, str(instance_id))
    if llm_type and llm_type != current_type:
        return str(instance_id), llm_type

    recommended_type = None
    if isinstance(agent2_decision, dict):
        recommended_type = agent2_decision.get("recommended_type")
    if not recommended_type:
        return None

    return str(instance_id), str(recommended_type)


def _llm_instance_type(parsed: dict[str, Any], instance_id: str) -> str | None:
    for container in (_matching_instance_output(parsed, instance_id), parsed):
        if not isinstance(container, dict):
            continue
        for field in (
            "new_instance_type",
            "recommended_type",
            "recommended_instance_type",
            "target_instance_type",
        ):
            value = container.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()

        terraform_block = container.get("terraform_block")
        if isinstance(terraform_block, str):
            match = re.search(r'(?m)^[ \t]*instance_type\s*=\s*"([^"]+)"', terraform_block)
            if match:
                return match.group(1)
    return None


def _matching_instance_output(parsed: dict[str, Any], instance_id: str) -> dict[str, Any] | None:
    instances = parsed.get("instances")
    if not isinstance(instances, dict):
        return None

    wanted = instance_id.strip().lower().replace("_", "-")
    for key, value in instances.items():
        if str(key).strip().lower().replace("_", "-") == wanted and isinstance(value, dict):
            return value
    return None


def _append_structured_ec2_patch_run(
    output: dict[str, Any],
    tf_file_map: dict[str, str],
) -> None:
    requested_updates: dict[str, str] = {}
    skipped: list[str] = []

    for run in output.get("runs", []):
        if not isinstance(run, dict) or run.get("scenario_type") != "ec2":
            continue
        update = _ec2_update_from_run(run)
        if update:
            instance_id, recommended_type = update
            requested_updates[instance_id] = recommended_type
            continue

        scenario = run.get("scenario")
        resource = _scenario_instance(scenario) if isinstance(scenario, dict) else None
        if resource:
            skipped.append(str(resource.get("instance_id") or "unknown"))

    if not requested_updates:
        if skipped:
            output.setdefault("structured_patch_warnings", []).append(
                "No EC2 instance_type updates were generated. "
                "Instances not patched because their Phase 3 decision was not DOWNSIZE: "
                + ", ".join(skipped)
            )
        return

    patched_main_tf, changed, warnings = apply_ec2_instance_type_updates(tf_file_map, requested_updates)
    if warnings:
        output.setdefault("structured_patch_warnings", []).extend(warnings)
    if not patched_main_tf or not changed:
        return

    changed_lines = [
        f"- {item.instance_id} ({item.module_name}): {item.old_type} -> {item.new_type}"
        for item in changed
    ]
    output["runs"].append(
        {
            "scenario_type": "terraform_patch",
            "scenario": {
                "source": "structured_ec2_instance_type_updates",
                "changed_instances": [
                    {
                        "instance_id": item.instance_id,
                        "module_name": item.module_name,
                        "old_type": item.old_type,
                        "new_type": item.new_type,
                        "file_path": item.file_path,
                    }
                    for item in changed
                ],
            },
            "llm": {
                "parsed": {
                    "verdict": "OPTIMAL",
                    "decision_summary": {
                        "action": "DOWNSIZE",
                        "decided_by": "AGENT_VALIDATED",
                        "rationale": (
                            "Phase 3 accepted the EC2 downsizing decision; "
                            "the backend applied only instance_type replacements."
                        ),
                    },
                    "technical_explanation": (
                        "Structured Terraform patch generated by replacing instance_type "
                        "inside matching EC2 module blocks in main.tf."
                    ),
                    "terraform_action": "LLM_GENERATED",
                    "modified_files": [
                        {
                            "file_path": changed[0].file_path,
                            "new_content": patched_main_tf,
                        }
                    ],
                    "pr_title": "Apply EC2 instance type optimizations",
                    "pr_description": "Structured EC2 instance type updates:\n" + "\n".join(changed_lines),
                }
            },
        }
    )


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
        phase1_by_key = _phase1_by_resource_key(ec2_phase1_results)
        validate_ec2_with_llm = _env_enabled("PHASE3_EC2_LLM_VALIDATION", "1")
        evaluate_all_ec2 = _env_enabled("PHASE3_EVALUATE_ALL_EC2")
        for phase2_result in ec2_phase2_results:
            key = _resource_key(phase2_result) or "unknown"
            instance_name = (
                _read(phase2_result, "instance_name")
                or _read(phase2_result, "resource_name")
                or _read(phase2_result, "instance_id")
                or key
            )
            scoped_terraform = scoped_terraform_for_instance(tf_file_map, str(instance_name))
            ec2_scenario = _single_ec2_scenario(
                phase1_by_key,
                phase2_result,
                current_terraform=scoped_terraform or tf_prompt_bundle,
            )
            is_patchable = _patchable_ec2_phase2(phase2_result)
            if is_patchable and validate_ec2_with_llm:
                system_prompt, user_prompt = _compact_ec2_validation_prompts(ec2_scenario)
                llm_result = _normalize_compact_ec2_result(
                    runner.run(system_prompt, user_prompt),
                    ec2_scenario,
                )
            elif is_patchable:
                llm_result = _synthetic_ec2_llm_result(
                    ec2_scenario,
                    phase2_result,
                    "Phase 2 produced a DOWNSIZE recommendation with a concrete target type; "
                    "Phase 3 generated a structured instance_type patch without an LLM rewrite.",
                )
            elif not is_patchable and not evaluate_all_ec2:
                llm_result = _synthetic_ec2_llm_result(
                    ec2_scenario,
                    phase2_result,
                    "Not auto-applied by Phase 3 because this EC2 finding is not a safe "
                    "instance_type-only DOWNSIZE candidate.",
                    verdict="NOT_EVALUATED",
                )
            else:
                system_prompt, user_prompt = prompt_builder.build_prompt(ec2_scenario)
                llm_result = _strip_ec2_generated_files(runner.run(system_prompt, user_prompt))
            output["runs"].append(
                {
                    "scenario_type": "ec2",
                    "scenario": ec2_scenario,
                    "llm": llm_result,
                }
            )

        if tf_file_map:
            _append_structured_ec2_patch_run(output, tf_file_map)
        else:
            output.setdefault("structured_patch_warnings", []).append(
                "No Terraform source was available; EC2 instance_type patches were not generated."
            )

    if s3_phase1_results and (_env_enabled("PHASE3_EVALUATE_S3") or not ec2_phase2_results):
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
    elif s3_phase1_results:
        output.setdefault("structured_patch_warnings", []).append(
            "S3 Phase 3 LLM evaluation was skipped for this dashboard run. "
            "Set PHASE3_EVALUATE_S3=1 to enable it once provider quota is available."
        )

    if not output["runs"]:
        output["note"] = "No EC2 Phase2 results or S3 findings to evaluate."

    patch_plan = extract_patch_plan(output)
    structured_patch_warnings = output.get("structured_patch_warnings")
    if isinstance(structured_patch_warnings, list):
        patch_plan.warnings.extend(str(warning) for warning in structured_patch_warnings)
    validation_errors = validate_patch_plan(patch_plan, tf_file_map) if patch_plan.modified_files else []
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
        "validation_errors": validation_errors,
    }
    output["patch_preview"] = {
        "modified_files": [
            {
                "file_path": modified_file.file_path,
                "original_content": tf_file_map.get(modified_file.file_path),
                "original_content_available": modified_file.file_path in tf_file_map,
                "new_content": modified_file.new_content,
            }
            for modified_file in patch_plan.modified_files
        ],
        "pr_title": patch_plan.pr_title,
        "pr_description": patch_plan.pr_description,
        "warnings": patch_plan.warnings,
        "validation_errors": validation_errors,
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
