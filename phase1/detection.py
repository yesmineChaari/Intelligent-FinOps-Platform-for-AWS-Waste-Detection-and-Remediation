"""
Phase 1 — Statistical Waste Detection
"""

import asyncpg
from .models import Phase1Result, WasteAction, WasteType, Rules
from .queries import (
    get_all_instances,
    get_instance_metrics,
    is_zombie,
    get_sizing_ladder,
    get_instance_price,
)
from .sizing import calculate_recommended_type


async def run_phase1(conn: asyncpg.Connection, rules: Rules) -> list[Phase1Result]:
    instances = await get_all_instances(conn)
    results = []

    for instance in instances:
        result = await _process_instance(conn, instance, rules)
        if result is not None:
            results.append(result)

    return results


async def _process_instance(
    conn: asyncpg.Connection,
    instance: dict,
    rules: Rules,
) -> Phase1Result:
    role = instance["role"]
    region = instance.get("region", "us-east-1")
    os_type = instance.get("os", "Linux")
    
    # 1. Global Zombie Check (Applies to all roles regardless of tagging)
    zombie = await is_zombie(conn, instance["instance_id"], rules.detection.zombie.stopped_days_threshold)
    if zombie:
        current_price = await get_instance_price(
            conn,
            instance["instance_type"],
            region,
            os_type,
        ) or 0.0
        return Phase1Result(
            instance_id=instance["instance_id"],
            role=role,
            action=rules.detection.zombie.action,
            waste_type=WasteType.ZOMBIE,
            detection_window_days=rules.detection.zombie.stopped_days_threshold,
            current_instance_type=instance["instance_type"],
            current_cost_per_hour=current_price,
            waste_per_month=round(current_price * 24 * 30, 2),
            detection_reason=f"Zombie: stopped for more than {rules.detection.zombie.stopped_days_threshold} days.",
        )
    
    # 2. Skip explicitly defined roles
    if role in rules.detection.skipped_roles:
        return _skip(instance["instance_id"], role)
    
    # 3. Role-based routing (detection logic), but preserve original DB role in output
    if role == "dependent_primary":
        return await _detect_dependent_primary(conn, instance, rules, role)
    elif role == "bursty":
        return await _detect_bursty(conn, instance, rules, role)
    else:
        # Any other role (including literal "steady" or typos) goes through steady logic
        return await _detect_steady(conn, instance, rules, role)


def _skip(instance_id: str, role: str) -> Phase1Result:
    return Phase1Result(
        instance_id=instance_id,
        role=role,
        action=WasteAction.SKIP,
        waste_type=WasteType.NONE,
        detection_reason="Instance role explicitly skipped in rules.yaml.",
    )


async def _detect_dependent_primary(
    conn: asyncpg.Connection,
    instance: dict,
    rules: Rules,
    role: str,
) -> Phase1Result:
    r = rules.detection.dependent_primary
    instance_id, instance_type = instance["instance_id"], instance["instance_type"]

    metrics = await get_instance_metrics(conn, instance_id, r.window_days)
    if not metrics:
        return _clean(instance_id, role, "No metric data available.")

    if metrics["p95_cpu"] < r.idle_p95_cpu_threshold and metrics["p95_ram"] < r.idle_p95_ram_threshold:
        sizing = await _get_sizing(conn, instance_type, metrics["p95_cpu"], metrics["p95_ram"], rules)
        return Phase1Result(
            instance_id=instance_id,
            role=role,
            action=r.action, # Explicit DOWNSIZE
            waste_type=WasteType.IDLE,
            detection_window_days=r.window_days,
            p95_cpu=metrics["p95_cpu"],
            p95_ram=metrics["p95_ram"],
            detection_reason=(
                f"Dependent primary idle: P95 CPU {metrics['p95_cpu']:.1f}% and P95 RAM {metrics['p95_ram']:.1f}% "
                f"below thresholds. Action forced to {r.action.value}."
            ),
            **(_flatten_sizing(sizing, instance_type, instance)),
        )

    return _clean(instance_id, role, "Thresholds not met.", metrics)


async def _detect_bursty(
    conn: asyncpg.Connection,
    instance: dict,
    rules: Rules,
    role: str,
) -> Phase1Result:
    r = rules.detection.bursty
    instance_id, instance_type = instance["instance_id"], instance["instance_type"]

    metrics = await get_instance_metrics(conn, instance_id, r.window_days)
    if not metrics:
        return _clean(instance_id, role, "No metric data available.")

    # Validation: Is it actually bursty? (The Cortez / Shen critique fix)
    if metrics["cv"] < r.cv_threshold:
        return Phase1Result(
            instance_id=instance_id,
            role=role,
            action=WasteAction.CLEAN, # Let agent handle the tag inconsistency warning
            waste_type=WasteType.TAG_ERROR,
            detection_window_days=r.window_days,
            cv=metrics["cv"],
            detection_reason=f"Tag inconsistency: Role is bursty, but Coefficient of Variation ({metrics['cv']:.2f}) < {r.cv_threshold}."
        )

    if metrics["p99_cpu"] < r.idle_p99_cpu_threshold:
        sizing = await _get_sizing(conn, instance_type, metrics["p99_cpu"], metrics["p95_ram"], rules)
        return Phase1Result(
            instance_id=instance_id,
            role="bursty",
            action=r.action,
            waste_type=WasteType.OVERSIZED,
            detection_window_days=r.window_days,
            p99_cpu=metrics["p99_cpu"],
            cv=metrics["cv"],
            p95_ram=metrics["p95_ram"],
            detection_reason=(
                f"Bursty oversized: Regular spikes confirmed (CV: {metrics['cv']:.2f}), "
                f"but P99 Peak CPU ({metrics['p99_cpu']:.1f}%) never needed full capacity."
            ),
            **(_flatten_sizing(sizing, instance_type, instance)),
        )

    return _clean(instance_id, role, f"P99 CPU {metrics['p99_cpu']:.1f}% exceeded threshold.", metrics)


async def _detect_steady(
    conn: asyncpg.Connection,
    instance: dict,
    rules: Rules,
    role: str,
) -> Phase1Result:
    r = rules.detection.steady
    instance_id, instance_type = instance["instance_id"], instance["instance_type"]
    last_metrics: dict | None = None
    region = instance.get("region", "us-east-1")
    os_type = instance.get("os", "Linux")

    # ── Check 1: Idle ──────────────────────────────────────
    idle_metrics = await get_instance_metrics(conn, instance_id, r.idle.window_days)
    if idle_metrics:
        last_metrics = idle_metrics
        if (idle_metrics["p95_cpu"] < r.idle.p95_cpu_threshold and 
            idle_metrics["p95_ram"] < r.idle.p95_ram_threshold and
            idle_metrics["max_cpu"] < r.idle.max_cpu_threshold):
            
            current_price = await get_instance_price(
                conn,
                instance_type,
                region,
                os_type,
            ) or 0.0
            return Phase1Result(
                instance_id=instance_id,
                role=role,
                action=r.idle.action,
                waste_type=WasteType.IDLE,
                detection_window_days=r.idle.window_days,
                p95_cpu=idle_metrics["p95_cpu"],
                p95_ram=idle_metrics["p95_ram"],
                max_cpu=idle_metrics["max_cpu"],
                current_instance_type=instance_type,
                current_cost_per_hour=current_price,
                waste_per_month=round(current_price * 24 * 30, 2),
                detection_reason="Steady Idle: P95 CPU, P95 RAM, and Max CPU below dead-idle thresholds."
            )

    # ── Check 2: Oversized ───────────────────────────────
    os_metrics = await get_instance_metrics(conn, instance_id, r.oversized.window_days)
    if os_metrics:
        last_metrics = os_metrics
        if (os_metrics["p95_cpu"] < r.oversized.p95_cpu_threshold and 
            os_metrics["p95_ram"] < r.oversized.p95_ram_threshold):
            
            sizing = await _get_sizing(conn, instance_type, os_metrics["p95_cpu"], os_metrics["p95_ram"], rules)
            return Phase1Result(
                instance_id=instance_id,
                role=role,
                action=r.oversized.action,
                waste_type=WasteType.OVERSIZED,
                detection_window_days=r.oversized.window_days,
                p95_cpu=os_metrics["p95_cpu"],
                p95_ram=os_metrics["p95_ram"],
                detection_reason=f"Steady Oversized: P95 CPU ({os_metrics['p95_cpu']:.1f}%) and P95 RAM ({os_metrics['p95_ram']:.1f}%) below capacity.",
                **(_flatten_sizing(sizing, instance_type, instance)),
            )

    return _clean(instance_id, role, "No waste pattern detected.", last_metrics)


def _clean(instance_id: str, role: str, reason: str, metrics: dict | None = None) -> Phase1Result:
    """Helper to generate clean results, optionally including computed metrics."""
    metrics = metrics or {}
    return Phase1Result(
        instance_id=instance_id,
        role=role,
        action=WasteAction.CLEAN,
        waste_type=WasteType.NONE,
        detection_window_days=None,
        p95_cpu=metrics.get("p95_cpu"),
        p99_cpu=metrics.get("p99_cpu"),
        max_cpu=metrics.get("max_cpu"),
        p95_ram=metrics.get("p95_ram"),
        cv=metrics.get("cv"),
        detection_reason=reason,
    )

# Inside detection.py
async def _get_sizing(
    conn: asyncpg.Connection,
    instance: dict,             
    cpu_to_project: float,
    ram_to_project: float,
    rules: Rules,
) -> dict | None:
    
    instance_type = instance["instance_type"]
    region = instance.get("region", "us-east-1") # fallback if not selected
    os_type = instance.get("os", "Linux")        # fallback if not selected
    
    # Extract family (e.g., "m5.large" -> "m5") to pass to the query
    instance_family = instance_type.split(".")[0]

    # Pass the region and OS down to the query
    ladder = await get_sizing_ladder(conn, instance_family, region, os_type)
    if not ladder: return None

    current_entry = next((e for e in ladder if e["instance_type"] == instance_type), None)
    if not current_entry: return None

    return calculate_recommended_type(
        current_type=instance_type,
        current_vcpus=current_entry["vcpu"], # using the new key
        current_ram_gb=current_entry["ram_gb"],
        current_price_per_hour=float(current_entry["price_per_hour"]),
        observed_cpu_pct=cpu_to_project,
        observed_ram_pct=ram_to_project,
        ladder=ladder,
        rules=rules.sizing,
    )

def _flatten_sizing(sizing: dict | None, instance_type: str, instance: dict) -> dict:
    if sizing is None:
        return {"current_instance_type": instance_type}
    return {
        "current_instance_type": instance_type,
        "recommended_type": sizing.get("recommended_type"),
        "projected_cpu_pct": sizing.get("projected_cpu_pct"),
        "projected_ram_pct": sizing.get("projected_ram_pct"),
        "recommended_cost_per_hour": sizing.get("recommended_cost_per_hour"),
        "waste_per_month": sizing.get("waste_per_month"),
    }