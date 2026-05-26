"""
Phase 1 — Statistical Waste Detection
"""

import logging

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


logger = logging.getLogger(__name__)


def _metrics_payload(result: Phase1Result) -> dict[str, float | int | bool | str]:
    payload: dict[str, float | int | bool | str] = {}
    for field in ("p95_cpu", "p99_cpu", "max_cpu", "p95_ram", "cv", 
                  "max_network_mbps", "max_disk_mbps", "p99_network_mbps", "p99_disk_mbps"):
        value = getattr(result, field, None)
        if value is not None:
            payload[field] = float(value)

    if result.stopped_days is not None:
        payload["stopped_days_since_last_metric"] = int(result.stopped_days)
    elif result.waste_type == WasteType.ZOMBIE:
        payload["stopped_days_since_last_metric"] = "unknown"
        payload["no_metrics_found"] = True

    return payload


def _log_instance_metrics(result: Phase1Result) -> None:
    metrics = _metrics_payload(result)
    if metrics:
        logger.info(
            "[Phase1][Metrics] resource_id=%s name=%s role=%s action=%s metrics=%s",
            result.resource_id,
            result.resource_name,
            result.role,
            result.action.value,
            metrics,
        )
    else:
        logger.info(
            "[Phase1][Metrics] resource_id=%s name=%s role=%s action=%s metrics={}",
            result.resource_id,
            result.resource_name,
            result.role,
            result.action.value,
        )


async def run_phase1(conn: asyncpg.Connection, rules: Rules) -> list[Phase1Result]:
    instances = await get_all_instances(conn)
    results = []

    for instance in instances:
        result = await _process_instance(conn, instance, rules)
        if result is not None:
            results.append(result)
            _log_instance_metrics(result)

    return results


async def _process_instance(
    conn: asyncpg.Connection,
    instance: dict,
    rules: Rules,
) -> Phase1Result:
    instance_role = instance["role"]
    region = instance.get("region", "us-east-1")
    os_type = instance.get("os", "linux")
    zombie_threshold = rules.detection.zombie.stopped_days_threshold
    
    # 1. Global Zombie Check (Applies to all roles regardless of tagging)
    zombie, stopped_days = await is_zombie(conn, instance["resource_id"], zombie_threshold)
    if instance.get("status") == "stopped":
        logger.info(
            "[Phase1][ZombieCheck] resource_id=%s name=%s stopped_days=%s threshold=%s zombie=%s",
            instance["resource_id"],
            instance["resource_name"],
            stopped_days if stopped_days is not None else "unknown",
            zombie_threshold,
            zombie,
        )

    if zombie:
        current_price = await get_instance_price(
            conn,
            instance["instance_type"],
            region,
            os_type,
        ) or 0.0
        return Phase1Result(
            resource_id=instance["resource_id"],
            resource_name=instance["resource_name"],
            role=instance_role,
            action=rules.detection.zombie.action,
            waste_type=WasteType.ZOMBIE,
            detection_window_days=zombie_threshold,
            stopped_days=stopped_days,
            current_instance_type=instance["instance_type"],
            current_cost_per_hour=current_price,
            waste_per_month=round(current_price * 24 * 30, 2),
            detection_reason=(
                f"Zombie: instance is stopped and last EC2 metric is {stopped_days} days old "
                f"(threshold={zombie_threshold})."
                if stopped_days is not None
                else (
                    "Zombie: instance is stopped and no EC2 metrics were found "
                    f"(threshold={zombie_threshold} days)."
                )
            ),
        )

    if instance.get("status") == "stopped" and stopped_days is not None and stopped_days < zombie_threshold:
        return Phase1Result(
            resource_id=instance["resource_id"],
            resource_name=instance["resource_name"],
            role=instance_role,
            action=WasteAction.REVIEW,
            waste_type=WasteType.STOPPED,
            detection_window_days=zombie_threshold,
            stopped_days=stopped_days,
            current_instance_type=instance["instance_type"],
            detection_reason=(
                f"Stopped but below zombie threshold: last EC2 metric is {stopped_days} days old "
                f"(< {zombie_threshold}). Review required before action."
            ),
        )
    # ── 1b. Running Zombie Check ──────────────────────────────────────
    if instance.get("status") == "running":
        r_zombie = rules.detection.zombie
        running_metrics = await get_instance_metrics(conn, instance["resource_id"], r_zombie.running_window_days)
        
        # Check if ALL three dimensions (CPU, Network, Disk) are essentially zero
        if running_metrics and (
            running_metrics["max_cpu"] < r_zombie.max_cpu_threshold and
            running_metrics.get("max_network_mbps", 0) < r_zombie.max_network_mbps_threshold and
            running_metrics.get("max_disk_mbps", 0) < r_zombie.max_disk_mbps_threshold
        ):
            current_price = await get_instance_price(conn, instance["instance_type"], region, os_type) or 0.0
            return Phase1Result(
                resource_id=instance["resource_id"],
                resource_name=instance["resource_name"],
                role=instance_role,
                action=r_zombie.action,
                waste_type=WasteType.ZOMBIE,
                detection_window_days=r_zombie.running_window_days,
                current_instance_type=instance["instance_type"],
                current_cost_per_hour=current_price,
                waste_per_month=round(current_price * 24 * 30, 2),
                max_cpu=running_metrics["max_cpu"],
                max_network_mbps=running_metrics.get("max_network_mbps"),
                max_disk_mbps=running_metrics.get("max_disk_mbps"),
                detection_reason=(
                    f"Running Zombie: Max CPU ({running_metrics['max_cpu']:.1f}%), "
                    f"Max Network ({running_metrics.get('max_network_mbps', 0):.1f} Mbps), "
                    f"and Max Disk ({running_metrics.get('max_disk_mbps', 0):.1f} Mbps) are all virtually zero over {r_zombie.running_window_days} days."
                ),
            )
    
    # 2. Skip explicitly defined roles
    if instance_role in rules.detection.skipped_roles:
        return _skip(instance["resource_id"], instance["resource_name"], instance_role)
    
    # 3. Role-based routing (detection logic)
    if instance_role == "dependant_primary":
        return await _detect_dependant_primary(conn, instance, rules, instance_role)
    elif instance_role == "bursty":
        return await _detect_bursty(conn, instance, rules, instance_role)
    else:
       
        return await _detect_steady(conn, instance, rules, instance_role)


def _skip(resource_id: int, resource_name: str, role: str) -> Phase1Result:
    return Phase1Result(
        resource_id=resource_id,
        resource_name=resource_name,
        role=role,
        action=WasteAction.SKIP,
        waste_type=WasteType.NONE,
        detection_reason="Instance role explicitly skipped in rules.yaml.",
    )


async def _detect_dependant_primary(
    conn: asyncpg.Connection,
    instance: dict,
    rules: Rules,
    role: str,
) -> Phase1Result:
    r = rules.detection.dependant_primary
    resource_id, resource_name, instance_type = instance["resource_id"], instance["resource_name"], instance["instance_type"]

    metrics = await get_instance_metrics(conn, resource_id, r.window_days)
    if not metrics:
        return _clean(resource_id, resource_name, role, "No metric data available.")

    if metrics["p95_cpu"] < r.idle_p95_cpu_threshold and metrics["p95_ram"] < r.idle_p95_ram_threshold:
        sizing = await _get_sizing(
            conn, instance, 
            metrics["p95_cpu"], metrics["p95_ram"], 
            metrics.get("p99_network_mbps", 0.0), metrics.get("p99_disk_mbps", 0.0), 
            rules
        )
        return Phase1Result(
            resource_id=resource_id,
            resource_name=resource_name,
            role=role,
            action=r.action, # Explicit DOWNSIZE
            waste_type=WasteType.IDLE,
            detection_window_days=r.window_days,
            p95_cpu=metrics["p95_cpu"],
            p99_cpu=metrics["p99_cpu"],
            max_cpu=metrics["max_cpu"],
            p95_ram=metrics["p95_ram"],
            cv=metrics["cv"],
            detection_reason=(
                f"Dependant primary idle: P95 CPU {metrics['p95_cpu']:.1f}% and P95 RAM {metrics['p95_ram']:.1f}% "
                f"below thresholds. Action forced to {r.action.value}."
            ),
            **(_flatten_sizing(sizing, instance_type, instance)),
        )

    return _clean(resource_id, resource_name, role, "Thresholds not met.", metrics)


async def _detect_bursty(
    conn: asyncpg.Connection,
    instance: dict,
    rules: Rules,
    role: str,
) -> Phase1Result:
    r = rules.detection.bursty
    resource_id, resource_name, instance_type = instance["resource_id"], instance["resource_name"], instance["instance_type"]

    metrics = await get_instance_metrics(conn, resource_id, r.window_days)
    if not metrics:
        return _clean(resource_id, resource_name, role, "No metric data available.")


    if metrics["cv"] < r.cv_threshold:
        return Phase1Result(
            resource_id=resource_id,
            resource_name=resource_name,
            role=role,
            action=WasteAction.REVIEW,
            waste_type=WasteType.TAG_ERROR,
            detection_window_days=r.window_days,
            p95_cpu=metrics["p95_cpu"],
            p99_cpu=metrics["p99_cpu"],
            max_cpu=metrics["max_cpu"],
            p95_ram=metrics["p95_ram"],
            cv=metrics["cv"],
            detection_reason=f"Tag inconsistency: Role is bursty, but Coefficient of Variation ({metrics['cv']:.2f}) < {r.cv_threshold}."
        )

    if metrics["p99_cpu"] < r.idle_p99_cpu_threshold:
        sizing = await _get_sizing(
            conn, instance, 
            metrics["p99_cpu"], metrics["p95_ram"], 
            metrics.get("p99_network_mbps", 0.0), metrics.get("p99_disk_mbps", 0.0), 
            rules
        )
        return Phase1Result(
            resource_id=resource_id,
            resource_name=resource_name,
            role="bursty",
            action=r.action,
            waste_type=WasteType.OVERSIZED,
            detection_window_days=r.window_days,
            p95_cpu=metrics["p95_cpu"],
            p99_cpu=metrics["p99_cpu"],
            max_cpu=metrics["max_cpu"],
            cv=metrics["cv"],
            p95_ram=metrics["p95_ram"],
            detection_reason=(
                f"Bursty oversized: Regular spikes confirmed (CV: {metrics['cv']:.2f}), "
                f"but P99 Peak CPU ({metrics['p99_cpu']:.1f}%) never needed full capacity."
            ),
            **(_flatten_sizing(sizing, instance_type, instance)),
        )

    return _clean(resource_id, resource_name, role, f"p99 CPU {metrics['p99_cpu']:.1f}% exceeded threshold of idle p99 cpu threshhold.", metrics)


async def _detect_steady(
    conn: asyncpg.Connection,
    instance: dict,
    rules: Rules,
    role: str,
) -> Phase1Result:
    r = rules.detection.steady
    resource_id, resource_name, instance_type = instance["resource_id"], instance["resource_name"], instance["instance_type"]
    last_metrics: dict | None = None
    region = instance.get("region", "us-east-1")
    os_type = instance.get("os", "linux")

    # ── Check 1: Idle ──────────────────────────────────────
    idle_metrics = await get_instance_metrics(conn, resource_id, r.idle.window_days)
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
                resource_id=resource_id,
                resource_name=resource_name,
                role=role,
                action=r.idle.action,
                waste_type=WasteType.IDLE,
                detection_window_days=r.idle.window_days,
                p95_cpu=idle_metrics["p95_cpu"],
                p99_cpu=idle_metrics["p99_cpu"],
                p95_ram=idle_metrics["p95_ram"],
                max_cpu=idle_metrics["max_cpu"],
                cv=idle_metrics["cv"],
                current_instance_type=instance_type,
                current_cost_per_hour=current_price,
                waste_per_month=round(current_price * 24 * 30, 2),
                detection_reason="Steady Idle: P95 CPU, P95 RAM, and Max CPU below dead-idle thresholds."
            )

    # ── Check 2: Oversized ───────────────────────────────
    os_metrics = await get_instance_metrics(conn, resource_id, r.oversized.window_days)
    if os_metrics:
        last_metrics = os_metrics
        if (os_metrics["p95_cpu"] < r.oversized.p95_cpu_threshold and 
            os_metrics["p95_ram"] < r.oversized.p95_ram_threshold):
            
            sizing = await _get_sizing(
                conn, instance, 
                os_metrics["p95_cpu"], os_metrics["p95_ram"], 
                os_metrics.get("p99_network_mbps", 0.0), os_metrics.get("p99_disk_mbps", 0.0), 
                rules
            )
            return Phase1Result(
                resource_id=resource_id,
                resource_name=resource_name,
                role=role,
                action=r.oversized.action,
                waste_type=WasteType.OVERSIZED,
                detection_window_days=r.oversized.window_days,
                p95_cpu=os_metrics["p95_cpu"],
                p99_cpu=os_metrics["p99_cpu"],
                p95_ram=os_metrics["p95_ram"],
                max_cpu=os_metrics["max_cpu"],
                cv=os_metrics["cv"],
                detection_reason=f"Steady Oversized: P95 CPU ({os_metrics['p95_cpu']:.1f}%) and P95 RAM ({os_metrics['p95_ram']:.1f}%) below capacity.",
                **(_flatten_sizing(sizing, instance_type, instance)),
            )

    if last_metrics is None:
        return _clean(resource_id, resource_name, role, "No metric data available.")

    return _clean(resource_id, resource_name, role, "No waste pattern detected.", last_metrics)


def _clean(resource_id: int, resource_name: str, role: str, reason: str, metrics: dict | None = None) -> Phase1Result:
    """Helper to generate clean results, optionally including computed metrics."""
    metrics = metrics or {}
    return Phase1Result(
        resource_id=resource_id,
        resource_name=resource_name,
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


async def _get_sizing(
    conn: asyncpg.Connection,
    instance: dict,             
    cpu_to_project: float,
    ram_to_project: float,
    network_to_project: float,  
    disk_to_project: float,     
    rules: Rules,
) -> dict | None:
    
    instance_type = instance["instance_type"]
    region = instance.get("region", "us-east-1") 
    os_type = instance.get("os", "Linux")      
    
    instance_family = instance_type.split(".")[0]

    ladder = await get_sizing_ladder(conn, instance_family, region, os_type)
    if not ladder: return None

    current_entry = next((e for e in ladder if e["instance_type"] == instance_type), None)
    if not current_entry: return None

    return calculate_recommended_type(
        current_type=instance_type,
        current_vcpus=current_entry["vcpu"], 
        current_ram_gb=current_entry["ram_gb"],
        current_price_per_hour=float(current_entry["price_per_hour"]),
        observed_cpu_pct=cpu_to_project,
        observed_ram_pct=ram_to_project,
        observed_network_mbps=network_to_project,  
        observed_disk_mbps=disk_to_project,        
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