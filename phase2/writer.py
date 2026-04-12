import logging

from phase2.models import Phase2Result
from phase2.queries import write_waste_rows


logger = logging.getLogger(__name__)


async def persist_phase2_results(conn, results: list[Phase2Result]) -> None:
    if not results:
        logger.info("[Phase2][Writer] No results to write.")
        return

    rows = []
    for result in results:
        rows.append(
            {
                "instance_id": result.instance_id,
                "waste_type": result.waste_type.value if hasattr(result.waste_type, "value") else result.waste_type,
                # Sentinel '0' means no detection window was used (e.g. zombie check).
                # Cannot be NULL — waste table enforces NOT NULL on this column.
                "detection_window": str(result.detection_window) if result.detection_window is not None else '0',
                # waste column 'avg_cpu'  stores P95 — column name is legacy, not semantic
                "avg_cpu": result.p95_cpu,
                # waste column 'peak_cpu' stores P99 — column name is legacy, not semantic
                "peak_cpu": result.p99_cpu,
                # waste column 'avg_ram'  stores P95 — column name is legacy, not semantic
                "avg_ram": result.p95_ram,
                "current_instance_type": result.current_instance_type,
                "recommended_type": result.recommended_type,
                "current_cost_per_hour": result.current_cost_per_hour,
                "recommended_cost_per_hour": result.recommended_cost_per_hour,
                "waste_per_month": result.waste_per_month,
                "action": result.action.value if hasattr(result.action, "value") else result.action,
                "safety_status": result.safety_status.value if hasattr(result.safety_status, "value") else result.safety_status,
                "block_reason": result.block_reason.value if result.block_reason else None,
                "pipeline_warning": result.pipeline_warning,
                "redundancy_node": result.redundancy_node,
                "depth_of_block": result.depth_of_block,
            }
        )

    logger.info(f"[Phase2][Writer] Writing {len(rows)} rows to waste table.")
    await write_waste_rows(conn, rows)
    logger.info("[Phase2][Writer] Waste table write complete.")
