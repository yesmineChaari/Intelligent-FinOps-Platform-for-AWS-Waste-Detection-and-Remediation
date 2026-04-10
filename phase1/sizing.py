"""
Sizing ladder — calculates the recommended downsize target safely predicting CPU & RAM.
"""
from typing import Optional
from .models import SizingRules

def calculate_recommended_type(
    current_type: str,
    current_vcpus: int,
    current_ram_gb: float,
    current_price_per_hour: float,
    observed_cpu_pct: float,
    observed_ram_pct: float,
    ladder: list[dict],
    rules: SizingRules,
) -> Optional[dict]:

    actual_ram_gb_consumed = (observed_ram_pct / 100.0) * current_ram_gb

    # FIXED: Use 'ladder_rank' instead of 'size_rank'
    current_rank = next((e["ladder_rank"] for e in ladder if e["instance_type"] == current_type), None)
    if current_rank is None:
        return None

    # FIXED: Filter and sort using 'ladder_rank'
    candidates_below = [e for e in ladder if e["ladder_rank"] < current_rank]
    candidates_below.sort(key=lambda x: x["ladder_rank"], reverse=True)

    best_candidate = None
    steps_dropped = 0

    for candidate in candidates_below:
        steps_dropped += 1

        if steps_dropped > rules.max_drop_steps:
            break

        # FIXED: Use 'vcpu' instead of 'vcpus'
        candidate_vcpus = candidate["vcpu"]
        candidate_ram_gb = candidate["ram_gb"]
        candidate_price = float(candidate["price_per_hour"])

        # ── CPU Projection ────────────────────────────────────────────────
        projected_cpu_pct = observed_cpu_pct * (current_vcpus / candidate_vcpus)

        if projected_cpu_pct >= rules.cpu_safety_ceiling:
            break

        # ── RAM Projection ────────────────────────────────────────────────
        projected_ram_pct = (actual_ram_gb_consumed / candidate_ram_gb) * 100.0

        if projected_ram_pct > rules.ram_headroom_threshold:
            break 

        # ── Passed ────────────────────────────────────────────────────────
        waste_per_month = (current_price_per_hour - candidate_price) * 24 * 30

        best_candidate = {
            "recommended_type": candidate["instance_type"],
            "projected_cpu_pct": round(projected_cpu_pct, 2),
            "projected_ram_pct": round(projected_ram_pct, 2),
            "recommended_cost_per_hour": candidate_price,
            "waste_per_month": round(waste_per_month, 2),
            "steps_dropped": steps_dropped,
        }

    return best_candidate