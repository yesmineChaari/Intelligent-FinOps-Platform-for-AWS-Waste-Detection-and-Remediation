import logging

import asyncpg

from phase1.models import Phase1Result, Phase2Rules, WasteAction
from phase2.models import Phase2Result, RelationshipEdge
from phase2.queries import load_local_relationships


logger = logging.getLogger(__name__)


def compute_blast_radius(relationships: list[RelationshipEdge], weights: dict[str, int]) -> int:
    return sum(int(weights.get(rel.relationship_type.lower(), 0)) for rel in relationships)


def _group_relationships(
    flagged_ids: set[int],
    relationships: list[RelationshipEdge],
) -> dict[int, list[RelationshipEdge]]:
    grouped: dict[int, list[RelationshipEdge]] = {resource_id: [] for resource_id in flagged_ids}

    for rel in relationships:
        if rel.resource_id in grouped:
            grouped[rel.resource_id].append(rel)
        if rel.related_resource_id in grouped and rel.related_resource_id != rel.resource_id:
            grouped[rel.related_resource_id].append(rel)

    return grouped


def _review_action_label(phase2_rules: Phase2Rules) -> WasteAction:
    label = phase2_rules.review_label.strip().upper()
    if label != WasteAction.REVIEW.value:
        logger.warning(
            "[Phase2] Unsupported review_label=%s in rules.yaml. Falling back to REVIEW.",
            phase2_rules.review_label,
        )
    return WasteAction.REVIEW


def _relationship_type_counts(local_relationships: list[RelationshipEdge]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for rel in local_relationships:
        rel_type = rel.relationship_type.lower()
        counts[rel_type] = counts.get(rel_type, 0) + 1
    return counts


def _format_relationship_counts(type_counts: dict[str, int]) -> str:
    if not type_counts:
        return "none"
    return ", ".join(f"{rel_type}:{count}" for rel_type, count in sorted(type_counts.items()))


def _build_blast_radius_explanation(
    relationship_type_counts: dict[str, int],
    blast_weights: dict[str, int],
    blast_radius_score: int,
    skip_context: str | None = None,
) -> str:
    weighted_terms: list[str] = []
    for rel_type, count in sorted(relationship_type_counts.items()):
        weight = int(blast_weights.get(rel_type, 0))
        if weight > 0:
            weighted_terms.append(f"{rel_type}({weight}x{count}={weight * count})")

    weighted_formula = " + ".join(weighted_terms) if weighted_terms else "no weighted relationships"
    base = f"blast_radius_score={blast_radius_score} computed as {weighted_formula}."

    if skip_context:
        return base + f" Scoring was not used for actioning because {skip_context}."

    return base


def _build_decision_details(
    phase1_action: WasteAction,
    phase2_action: WasteAction,
    blast_radius_score: int,
    relationship_type_counts: dict[str, int],
    has_writes_or_logs: bool,
    phase2_rules: Phase2Rules,
    reason: str,
) -> str:
    blast_rules = phase2_rules.blast_radius
    return (
        f"phase1_action={phase1_action.value}; "
        f"phase2_action={phase2_action.value}; "
        f"blast_radius_score={blast_radius_score}; "
        f"relationship_types=[{_format_relationship_counts(relationship_type_counts)}]; "
        f"has_writes_or_logs={has_writes_or_logs}; "
        "thresholds="
        f"(terminate_max_score={blast_rules.terminate_max_score}, "
        f"stop_max_score={blast_rules.stop_max_score}, "
        f"downsize_max_score={blast_rules.downsize_max_score}); "
        f"decision_reason={reason}"
    )


def _downgrade_action(
    phase1_action: WasteAction,
    blast_radius_score: int,
    has_writes_or_logs: bool,
    phase2_rules: Phase2Rules,
) -> tuple[WasteAction, str | None]:
    review_action = _review_action_label(phase2_rules)
    blast_rules = phase2_rules.blast_radius

    if phase1_action == WasteAction.TERMINATE:
        if blast_radius_score > blast_rules.terminate_max_score:
            return (
                review_action,
                (
                    "Guardrail B: TERMINATE downgraded to REVIEW because "
                    f"blast_radius_score={blast_radius_score} exceeds {blast_rules.terminate_max_score}."
                ),
            )
        return phase1_action, None

    if phase1_action == WasteAction.STOP:
        if has_writes_or_logs:
            return (
                WasteAction.DOWNSIZE,
                "Guardrail B: STOP downgraded to DOWNSIZE because writes_to or sends_logs_to dependencies exist.",
            )
        if blast_radius_score > blast_rules.stop_max_score:
            return (
                review_action,
                (
                    "Guardrail B: STOP downgraded to REVIEW because "
                    f"blast_radius_score={blast_radius_score} exceeds {blast_rules.stop_max_score}."
                ),
            )
        return phase1_action, None

    if phase1_action == WasteAction.DOWNSIZE:
        if blast_radius_score > blast_rules.downsize_max_score:
            return (
                review_action,
                (
                    "Guardrail B: DOWNSIZE downgraded to REVIEW because "
                    f"blast_radius_score={blast_radius_score} exceeds {blast_rules.downsize_max_score}."
                ),
            )
        return phase1_action, None

    if phase1_action == WasteAction.REVIEW:
        return phase1_action, "Guardrail B: REVIEW retained from Phase 1."

    return phase1_action, None


async def run_phase2(
    conn: asyncpg.Connection,
    phase1_results: list[Phase1Result],
    phase2_rules: Phase2Rules,
) -> list[Phase2Result]:
    """Run Phase 2 graph-aware guardrails on Phase 1 flagged instances."""
    if not phase1_results:
        logger.info("[Phase2] No Phase 1 results received.")
        return []

    blast_weights = {
        relationship_type.lower(): int(weight)
        for relationship_type, weight in phase2_rules.weighted_relationships.items()
    }

    bypassed = [r for r in phase1_results if r.action in (WasteAction.CLEAN, WasteAction.SKIP)]
    flagged = [r for r in phase1_results if r.action not in (WasteAction.CLEAN, WasteAction.SKIP)]

    output: list[Phase2Result] = []

    for result in bypassed:
        phase2_reason = (
            "Phase 2 skipped: resource is not eligible for graph guardrails because "
            f"Phase 1 action is {result.action.value}."
        )
        output.append(
            Phase2Result(
                resource_id=result.resource_id,
                resource_name=result.resource_name,
                role=result.role,
                waste_type=result.waste_type,
                phase1_action=result.action,
                action=result.action,
                detection_reason=result.detection_reason,
                phase2_action=WasteAction.SKIP,
                phase2_action_changed=WasteAction.SKIP != result.action,
                phase2_action_reason=phase2_reason,
                phase2_decision_details=_build_decision_details(
                    phase1_action=result.action,
                    phase2_action=WasteAction.SKIP,
                    blast_radius_score=0,
                    relationship_type_counts={},
                    has_writes_or_logs=False,
                    phase2_rules=phase2_rules,
                    reason=phase2_reason,
                ),
                blast_radius_explanation=_build_blast_radius_explanation(
                    relationship_type_counts={},
                    blast_weights=blast_weights,
                    blast_radius_score=0,
                    skip_context="resource was not eligible for Phase 2 scoring",
                ),
                blast_radius_score=0,
                relationship_count=0,
                skip_write=True,
                guardrail_reason=phase2_reason,
                detection_window_days=result.detection_window_days,
                stopped_days=result.stopped_days,
                current_instance_type=result.current_instance_type,
                recommended_type=result.recommended_type,
                current_cost_per_hour=result.current_cost_per_hour,
                recommended_cost_per_hour=result.recommended_cost_per_hour,
                waste_per_month=result.waste_per_month,
            )
        )

    if not flagged:
        logger.info("[Phase2] No graph-eligible resources. Returning %s skipped entries.", len(output))
        return output

    flagged_ids = sorted({r.resource_id for r in flagged})
    relationships = await load_local_relationships(conn, flagged_ids)
    grouped_relationships = _group_relationships(set(flagged_ids), relationships)

    type_e_relationships = {rel_type.lower() for rel_type in phase2_rules.type_e_relationships}

    for result in flagged:
        local_relationships = grouped_relationships.get(result.resource_id, [])
        local_types = [rel.relationship_type.lower() for rel in local_relationships]
        relationship_type_counts = _relationship_type_counts(local_relationships)

        type_e_hits = sorted({rel_type for rel_type in local_types if rel_type in type_e_relationships})
        if type_e_hits:
            phase2_reason = (
                "Guardrail A: high-availability relationship detected "
                f"({', '.join(type_e_hits)}). Action skipped, no write."
            )
            phase2_action = WasteAction.SKIP
            blast_explanation = _build_blast_radius_explanation(
                relationship_type_counts=relationship_type_counts,
                blast_weights=blast_weights,
                blast_radius_score=0,
                skip_context="Guardrail A (Type-E) forced SKIP",
            )
            output.append(
                Phase2Result(
                    resource_id=result.resource_id,
                    resource_name=result.resource_name,
                    role=result.role,
                    waste_type=result.waste_type,
                    phase1_action=result.action,
                    action=result.action,
                    detection_reason=result.detection_reason,
                    phase2_action=phase2_action,
                    phase2_action_changed=phase2_action != result.action,
                    phase2_action_reason=phase2_reason,
                    phase2_decision_details=_build_decision_details(
                        phase1_action=result.action,
                        phase2_action=phase2_action,
                        blast_radius_score=0,
                        relationship_type_counts=relationship_type_counts,
                        has_writes_or_logs=False,
                        phase2_rules=phase2_rules,
                        reason=phase2_reason,
                    ),
                    blast_radius_explanation=blast_explanation,
                    blast_radius_score=0,
                    relationship_count=len(local_relationships),
                    skip_write=True,
                    guardrail_reason=phase2_reason,
                    detection_window_days=result.detection_window_days,
                    stopped_days=result.stopped_days,
                    current_instance_type=result.current_instance_type,
                    recommended_type=result.recommended_type,
                    current_cost_per_hour=result.current_cost_per_hour,
                    recommended_cost_per_hour=result.recommended_cost_per_hour,
                    waste_per_month=result.waste_per_month,
                )
            )
            continue

        blast_radius_score = compute_blast_radius(local_relationships, blast_weights)
        has_writes_or_logs = any(rel_type in {"writes_to", "sends_logs_to"} for rel_type in local_types)

        final_action, reason = _downgrade_action(
            phase1_action=result.action,
            blast_radius_score=blast_radius_score,
            has_writes_or_logs=has_writes_or_logs,
            phase2_rules=phase2_rules,
        )

        phase2_reason = reason or "No downgrade applied. Phase 1 action retained."
        blast_explanation = _build_blast_radius_explanation(
            relationship_type_counts=relationship_type_counts,
            blast_weights=blast_weights,
            blast_radius_score=blast_radius_score,
        )

        output.append(
            Phase2Result(
                resource_id=result.resource_id,
                resource_name=result.resource_name,
                role=result.role,
                waste_type=result.waste_type,
                phase1_action=result.action,
                action=result.action,
                detection_reason=result.detection_reason,
                phase2_action=final_action,
                phase2_action_changed=final_action != result.action,
                phase2_action_reason=phase2_reason,
                phase2_decision_details=_build_decision_details(
                    phase1_action=result.action,
                    phase2_action=final_action,
                    blast_radius_score=blast_radius_score,
                    relationship_type_counts=relationship_type_counts,
                    has_writes_or_logs=has_writes_or_logs,
                    phase2_rules=phase2_rules,
                    reason=phase2_reason,
                ),
                blast_radius_explanation=blast_explanation,
                blast_radius_score=blast_radius_score,
                relationship_count=len(local_relationships),
                skip_write=False,
                guardrail_reason=phase2_reason,
                detection_window_days=result.detection_window_days,
                stopped_days=result.stopped_days,
                current_instance_type=result.current_instance_type,
                recommended_type=result.recommended_type,
                current_cost_per_hour=result.current_cost_per_hour,
                recommended_cost_per_hour=result.recommended_cost_per_hour,
                waste_per_month=result.waste_per_month,
            )
        )

    logger.info(
        "[Phase2] Completed guardrails for %s resources (%s evaluated, %s skipped).",
        len(output),
        len(flagged),
        len(bypassed),
    )
    return output
