from __future__ import annotations

from typing import Any, Iterable


def _enum_value(value: Any) -> Any:
    if value is None:
        return None
    return getattr(value, "value", value)


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def build_ec2_scenario(
    phase1_results: Iterable[Any],
    phase2_results: Iterable[Any],
    *,
    scenario_id: str = "A_auto",
    description: str = "Auto-generated EC2 scenario from Phase1/Phase2 outputs",
    terraform_mode: int = 1,
    app_group: str = "AUTO",
    current_terraform: str = "",
) -> dict[str, Any]:
    """Build an EC2 scenario compatible with prompt_builder.build_prompt().

    Note: This does NOT mutate the Phase1/Phase2 objects.
    """

    phase1_by_id: dict[int, Any] = {}
    for r in phase1_results:
        rid = getattr(r, "resource_id", None)
        if rid is None:
            continue
        try:
            phase1_by_id[int(rid)] = r
        except (TypeError, ValueError):
            continue

    flagged_resources: list[dict[str, Any]] = []

    for p2 in phase2_results:
        rid_any = getattr(p2, "resource_id", None)
        if rid_any is None:
            continue
        try:
            rid = int(rid_any)
        except (TypeError, ValueError):
            continue

        p1 = phase1_by_id.get(rid)

        agent2_action = _enum_value(_coalesce(getattr(p2, "phase2_action", None), getattr(p2, "action", None)))
        phase1_action = _enum_value(_coalesce(getattr(p1, "action", None), getattr(p2, "phase1_action", None)))
        action = agent2_action or phase1_action
        if action in ("SKIP", "REVIEW"):
            action = "KEEP"
        elif action == "CLEAN":
            action = "NONE"

        waste_type = _enum_value(_coalesce(getattr(p1, "waste_type", None), getattr(p2, "waste_type", None)))
        detection_reason = _coalesce(getattr(p1, "detection_reason", None), getattr(p2, "detection_reason", None))

        phase2_reason = getattr(p2, "phase2_action_reason", None)
        if phase2_reason:
            if detection_reason:
                detection_reason = f"{detection_reason} | Phase2: {phase2_reason}"
            else:
                detection_reason = f"Phase2: {phase2_reason}"

        block_reason = _coalesce(getattr(p2, "block_reason", None), getattr(p2, "guardrail_reason", None))

        agent2_decision: dict[str, Any] = {
            "action": action,
            "waste_type": waste_type,
            "detection_reason": detection_reason,
        }

        detection_window_days = _coalesce(getattr(p1, "detection_window_days", None), getattr(p2, "detection_window_days", None))
        if detection_window_days is not None:
            agent2_decision["detection_window_days"] = int(detection_window_days)

        if block_reason:
            agent2_decision["block_reason"] = str(block_reason)

        p95_cpu = _coalesce(getattr(p1, "p95_cpu", None), getattr(p2, "p95_cpu", None))
        if p95_cpu is not None:
            p99_cpu = _coalesce(getattr(p1, "p99_cpu", None), getattr(p2, "p99_cpu", None))
            max_cpu = _coalesce(getattr(p1, "max_cpu", None), getattr(p2, "max_cpu", None))
            p95_ram = _coalesce(getattr(p1, "p95_ram", None), getattr(p2, "p95_ram", None))
            cv = _coalesce(getattr(p1, "cv", None), getattr(p2, "cv", None))

            try:
                agent2_decision["p95_cpu"] = float(p95_cpu)
            except (TypeError, ValueError):
                agent2_decision["p95_cpu"] = None

            try:
                agent2_decision["p99_cpu"] = float(p99_cpu) if p99_cpu is not None else None
            except (TypeError, ValueError):
                agent2_decision["p99_cpu"] = None

            try:
                agent2_decision["max_cpu"] = float(max_cpu) if max_cpu is not None else None
            except (TypeError, ValueError):
                agent2_decision["max_cpu"] = None

            if p95_ram is not None:
                try:
                    agent2_decision["p95_ram"] = float(p95_ram)
                except (TypeError, ValueError):
                    pass

            if cv is not None:
                try:
                    agent2_decision["cv"] = float(cv)
                except (TypeError, ValueError):
                    pass

        stopped_days = _coalesce(getattr(p1, "stopped_days", None), getattr(p2, "stopped_days", None))
        if stopped_days is not None:
            try:
                agent2_decision["stopped_days"] = int(stopped_days)
            except (TypeError, ValueError):
                pass

        recommended_type = _coalesce(getattr(p1, "recommended_type", None), getattr(p2, "recommended_type", None))
        if recommended_type:
            agent2_decision["recommended_type"] = str(recommended_type)

        blast_radius = _coalesce(getattr(p2, "blast_radius", None), getattr(p2, "blast_radius_score", None))
        if blast_radius is not None:
            try:
                agent2_decision["blast_radius"] = int(blast_radius)
            except (TypeError, ValueError):
                pass

        resource_name = _coalesce(
            getattr(p2, "instance_name", None),
            getattr(p1, "resource_name", None),
            getattr(p2, "resource_name", None),
        )
        instance_id = str(_coalesce(resource_name, rid))
        instance_name = str(_coalesce(resource_name, instance_id))

        current_instance_type = _coalesce(
            getattr(p2, "instance_type", None),
            getattr(p1, "current_instance_type", None),
            getattr(p2, "current_instance_type", None),
        )

        resource_entry: dict[str, Any] = {
            "instance_id": instance_id,
            "instance_name": instance_name,
            "instance_type": str(current_instance_type) if current_instance_type else None,
            "role": _coalesce(getattr(p1, "role", None), getattr(p2, "role", None)),
            "status": getattr(p1, "status", None),
            "os": getattr(p1, "os", None),
            "region": getattr(p1, "region", None),
            "environment": getattr(p1, "environment", None),
            "relationships": [],
            "agent2_decision": agent2_decision,
        }

        current_cost_per_hour = _coalesce(
            getattr(p1, "current_cost_per_hour", None),
            getattr(p2, "current_cost_per_hour", None),
        )
        recommended_cost_per_hour = _coalesce(
            getattr(p1, "recommended_cost_per_hour", None),
            getattr(p2, "recommended_cost_per_hour", None),
        )
        waste_per_month = _coalesce(getattr(p1, "waste_per_month", None), getattr(p2, "waste_per_month", None))

        def _safe_float(value: Any, default: float) -> float:
            if value is None:
                return default
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        cost: dict[str, Any] = {
            "current_cost_per_hour": _safe_float(current_cost_per_hour, 0.0),
            "recommended_cost_per_hour": None,
            "waste_per_month": _safe_float(waste_per_month, 0.0),
        }
        if recommended_cost_per_hour is not None:
            try:
                cost["recommended_cost_per_hour"] = float(recommended_cost_per_hour)
            except (TypeError, ValueError):
                cost["recommended_cost_per_hour"] = None

        resource_entry["cost"] = cost

        flagged_resources.append(resource_entry)

    return {
        "scenario_id": scenario_id,
        "description": description,
        "terraform_mode": terraform_mode,
        "app_group": app_group,
        "flagged_resources": flagged_resources,
        "current_terraform": current_terraform,
        "llm_evaluation": {},
    }


def build_s3_scenario(
    s3_results: list[Any],
    *,
    scenario_id: str = "C_auto",
    description: str = "Auto-generated S3 scenario from Phase1 outputs",
    terraform_mode: int = 2,
) -> dict[str, Any]:
    """Build a Tier-C (non-EC2) scenario for S3 findings."""

    def _normalize_s3_action(action_value: Any) -> Any:
        val = _enum_value(action_value)
        if val == "RECOMMEND_LIFECYCLE":
            return "GLACIER_TRANSITION"
        if val in ("CLEAN", "REVIEW"):
            return "NONE"
        return val

    def _finding_for_result(r: Any) -> dict[str, Any]:
        return {
            "finding_type": _normalize_s3_action(getattr(r, "action", None)) or "S3_OPTIMIZATION",
            "resource_type": "s3_bucket",
            "bucket_name": getattr(r, "bucket_name", None),
            "grouping_key": getattr(r, "grouping_key", None),
            "has_lifecycle": getattr(r, "has_lifecycle", None),
            "total_requests_30d": getattr(r, "total_requests_30d", None),
            "object_count": getattr(r, "object_count", None),
            "pct_older_90_days": getattr(r, "pct_older_90_days", None),
            "estimated_monthly_savings": getattr(r, "estimated_monthly_savings", None),
            "detection_reason": getattr(r, "detection_reason", None),
        }

    def _decision_for_result(r: Any) -> dict[str, Any]:
        original_action = _enum_value(getattr(r, "action", None))
        action = _normalize_s3_action(original_action)

        decision = {
            "action": action,
            "waste_type": _enum_value(getattr(r, "waste_type", None)),
            "detection_window_days": getattr(r, "detection_window_days", None),
            "detection_reason": getattr(r, "detection_reason", None),
            "blast_radius": None,
        }
        if original_action == "REVIEW":
            decision["block_reason"] = "Needs manual review"
        return decision

    if not s3_results:
        return {
            "scenario_id": scenario_id,
            "description": description,
            "terraform_mode": terraform_mode,
            "finding": {},
            "agent2_decision": {},
            "current_terraform": "",
            "llm_evaluation": {},
        }

    if len(s3_results) == 1:
        r = s3_results[0]
        return {
            "scenario_id": scenario_id,
            "description": description,
            "terraform_mode": terraform_mode,
            "finding": _finding_for_result(r),
            "agent2_decision": _decision_for_result(r),
            "current_terraform": "",
            "llm_evaluation": {},
        }

    findings: list[dict[str, Any]] = []
    for r in s3_results:
        bucket = getattr(r, "bucket_name", None) or "unknown_bucket"
        grouping = getattr(r, "grouping_key", None)
        resource_id = str(bucket if not grouping else f"{bucket}:{grouping}")
        findings.append(
            {
                "resource_id": resource_id,
                "finding": _finding_for_result(r),
                "agent2_decision": _decision_for_result(r),
                "current_terraform": "",
            }
        )

    return {
        "scenario_id": scenario_id,
        "description": description,
        "terraform_mode": terraform_mode,
        "findings": findings,
        "llm_evaluation": {},
    }
