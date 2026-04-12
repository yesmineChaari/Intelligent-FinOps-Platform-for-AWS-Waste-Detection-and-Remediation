import logging

import asyncpg

from phase1.models import Phase1Result, WasteAction
from phase2.models import (
    BlockReason,
    CAPPED_ROLES,
    PROTECTED_ROLES,
    Phase2Action,
    Phase2Result,
    SafetyStatus,
    STEADY_LIKE_ROLES,
    TYPE_A,
    TYPE_B,
    TYPE_C,
    TYPE_E,
    TYPE_E_ELIGIBLE_ROLES,
)
from phase2.queries import (
    check_type_e_redundancy,
    count_active_lb_targets,
    get_upstream_callers,
)


logger = logging.getLogger(__name__)


def _generate_terraform_block(
    instance_id: str,
    action: Phase2Action,
    target_type: str | None = None,
) -> str | None:
    if action == Phase2Action.TERMINATE:
        return (
            f"# FINOPS: TERMINATE {instance_id}\n"
            f"# Run: terraform destroy -target=aws_instance.{instance_id}\n"
            f"# Ensure no remaining dependants before applying."
        )
    if action == Phase2Action.STOP:
        return (
            f"# FINOPS: STOP {instance_id}\n"
            f"# Run: aws ec2 stop-instances --instance-ids {instance_id}"
        )
    if action == Phase2Action.DOWNSIZE and target_type:
        return (
            f"# FINOPS: DOWNSIZE {instance_id} → {target_type}\n"
            f"# In your Terraform resource block, change:\n"
            f'#   instance_type = "{target_type}"'
        )
    return None


def _get_phase2_metric(source: Phase1Result, primary: str, fallback: str | None = None):
    value = getattr(source, primary, None)
    if value is not None:
        return value
    if fallback is not None:
        return getattr(source, fallback, None)
    return None


def _make_result(
    source: Phase1Result,
    action: Phase2Action,
    safety_status: SafetyStatus,
    block_reason: BlockReason | None = None,
    fallback_action: Phase2Action | None = None,
    pipeline_warning: bool = False,
    redundancy_node: bool = False,
    depth_of_block: int | None = None,
    terraform_block: str | None = None,
    fallback_terraform_block: str | None = None,
) -> Phase2Result:
    return Phase2Result(
        instance_id=source.instance_id,
        role=source.role,
        waste_type=source.waste_type,
        detection_window=_get_phase2_metric(source, "detection_window", "detection_window_days"),
        p95_cpu=source.p95_cpu,
        p99_cpu=getattr(source, 'p99_cpu', None) or getattr(source, 'max_cpu', None),
        p95_ram=source.p95_ram,
        current_instance_type=source.current_instance_type,
        recommended_type=source.recommended_type,
        current_cost_per_hour=source.current_cost_per_hour,
        recommended_cost_per_hour=source.recommended_cost_per_hour,
        waste_per_month=source.waste_per_month,
        action=action,
        safety_status=safety_status,
        block_reason=block_reason,
        fallback_action=fallback_action,
        pipeline_warning=pipeline_warning,
        redundancy_node=redundancy_node,
        depth_of_block=depth_of_block,
        terraform_block=terraform_block,
        fallback_terraform_block=fallback_terraform_block,
    )


def _step0(result: Phase1Result) -> tuple[Phase2Result | None, bool]:
    if result.role in PROTECTED_ROLES:
        return (
            _make_result(
                source=result,
                action=Phase2Action.NEEDS_REVIEW,
                safety_status=SafetyStatus.NEEDS_REVIEW,
                block_reason=BlockReason.protected_role,
                fallback_action=None,
                terraform_block=None,
            ),
            False,
        )

    action_cap_applied = False
    if result.role in CAPPED_ROLES and result.action in (WasteAction.TERMINATE, WasteAction.STOP):
        result = result.model_copy(update={"action": WasteAction.DOWNSIZE})
        action_cap_applied = True

    return (None, action_cap_applied)


async def _step1(conn: asyncpg.Connection, result: Phase1Result) -> Phase2Result | None:
    if result.role not in TYPE_E_ELIGIBLE_ROLES:
        return None

    is_redundancy_target = await check_type_e_redundancy(conn, result.instance_id)
    if is_redundancy_target:
        logger.info(
            f"[Phase2][Step1] {result.instance_id} is a TYPE_E redundancy target - overriding to NEEDS_REVIEW"
        )
        return _make_result(
            source=result,
            action=Phase2Action.NEEDS_REVIEW,
            safety_status=SafetyStatus.NEEDS_REVIEW,
            block_reason=BlockReason.redundancy_node,
            redundancy_node=True,
            fallback_action=None,
            terraform_block=None,
        )

    return None


def _step3(
    result: Phase1Result,
    action_cap_applied: bool,
    pipeline_warning: bool = False,
) -> Phase2Result:
    final_action = Phase2Action(result.action.value)
    terraform = _generate_terraform_block(result.instance_id, final_action, result.recommended_type)

    logger.info(
        f"[Phase2][Step3] {result.instance_id} -> SAFE | action={final_action.value}"
    )

    return _make_result(
        source=result,
        action=final_action,
        safety_status=SafetyStatus.SAFE,
        block_reason=None,
        fallback_action=None,
        pipeline_warning=pipeline_warning,
        redundancy_node=False,
        depth_of_block=None,
        terraform_block=terraform,
        fallback_terraform_block=None,
    )


async def _step2(
    conn: asyncpg.Connection,
    result: Phase1Result,
    action_cap_applied: bool,
) -> Phase2Result:
    callers = await get_upstream_callers(conn, result.instance_id, max_depth=3)

    if not callers:
        return _step3(result, action_cap_applied)

    pipeline_warning = False
    hard_blocked = False
    block_reason = None
    depth_of_block = None
    fallback_action = None
    fallback_terraform = None

    current_action = Phase2Action(result.action.value)

    for caller in callers:
        rel_type = caller["relationship_type"]
        depth = caller["depth"]
        source_id = caller["source_id"]

        if rel_type in TYPE_A:
            if current_action in (Phase2Action.TERMINATE, Phase2Action.STOP):
                hard_blocked = True
                block_reason = BlockReason.active_upstream_type_A
                depth_of_block = depth
                if result.recommended_type and result.recommended_cost_per_hour is not None:
                    fallback_action = Phase2Action.DOWNSIZE
                    fallback_terraform = _generate_terraform_block(
                        result.instance_id,
                        Phase2Action.DOWNSIZE,
                        result.recommended_type,
                    )
                logger.info(
                    f"[Phase2][Step2] {result.instance_id} blocked by TYPE_A caller {source_id} at depth {depth}"
                )
                break

        elif rel_type in TYPE_B:
            other_target_count = await count_active_lb_targets(conn, source_id)
            if other_target_count == 0 and current_action == Phase2Action.TERMINATE:
                hard_blocked = True
                block_reason = BlockReason.last_routing_target
                depth_of_block = depth
                if result.recommended_type and result.recommended_cost_per_hour is not None:
                    fallback_action = Phase2Action.DOWNSIZE
                    fallback_terraform = _generate_terraform_block(
                        result.instance_id,
                        Phase2Action.DOWNSIZE,
                        result.recommended_type,
                    )
                logger.info(
                    f"[Phase2][Step2] {result.instance_id} is last LB target of {source_id} - blocking TERMINATE"
                )
                break

        elif rel_type in TYPE_C:
            pipeline_warning = True
            logger.info(
                f"[Phase2][Step2] {result.instance_id} has async TYPE_C caller {source_id} - setting pipeline_warning=True, action unchanged"
            )

        elif rel_type in TYPE_A | TYPE_B | TYPE_C | TYPE_E:
            logger.info(
                f"[Phase2][Step2] {result.instance_id} encountered relationship {rel_type} from {source_id} at depth {depth}"
            )

    if hard_blocked:
        return _make_result(
            source=result,
            action=Phase2Action.NEEDS_REVIEW,
            safety_status=SafetyStatus.NEEDS_REVIEW,
            block_reason=block_reason,
            fallback_action=fallback_action,
            pipeline_warning=pipeline_warning,
            depth_of_block=depth_of_block,
            terraform_block=None,
            fallback_terraform_block=fallback_terraform,
        )

    return _step3(result, action_cap_applied, pipeline_warning=pipeline_warning)


async def _process_guardrails(conn: asyncpg.Connection, result: Phase1Result) -> Phase2Result:
    logger.info(f"[Phase2] Processing {result.instance_id} | role={result.role} | action={result.action}")

    early_result, action_cap_applied = _step0(result)
    if early_result is not None:
        logger.info(f"[Phase2][Step0] {result.instance_id} -> NEEDS_REVIEW (protected_role)")
        return early_result

    if action_cap_applied:
        result = result.model_copy(update={"action": WasteAction.DOWNSIZE})
        logger.info(f"[Phase2][Step0] {result.instance_id} dependant_primary action capped to DOWNSIZE")

    redundancy_result = await _step1(conn, result)
    if redundancy_result is not None:
        return redundancy_result

    return await _step2(conn, result, action_cap_applied)


async def run_phase2(conn: asyncpg.Connection, phase1_results: list[Phase1Result]) -> list[Phase2Result]:
    logger.info(f"[Phase2] Starting. Received {len(phase1_results)} Phase 1 results.")
    output: list[Phase2Result] = []

    for result in phase1_results:
        # Exclude SKIP: protected or irrelevant resources, no waste to record.
        # Exclude CLEAN: resource already remediated — writing it to the waste
        # table would falsely imply it remains wasteful. Adopted as explicit
        # policy (Option A) — this is intentional, not an oversight.
        if result.action in (WasteAction.SKIP, WasteAction.CLEAN):
            logger.info(f"[Phase2] Skipping {result.instance_id} ({result.action.value} action from Phase 1)")
            continue

        phase2_result = await _process_guardrails(conn, result)
        output.append(phase2_result)

    logger.info(f"[Phase2] Complete. {len(output)} results ready for waste table write.")
    return output
