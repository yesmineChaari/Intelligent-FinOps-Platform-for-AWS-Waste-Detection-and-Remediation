from enum import Enum

from pydantic import BaseModel

from phase1.models import WasteAction, WasteType


class SafetyStatus(str, Enum):
    SAFE = "SAFE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class BlockReason(str, Enum):
    active_upstream_type_A = "active_upstream_type_A"
    last_routing_target = "last_routing_target"
    redundancy_node = "redundancy_node"
    protected_role = "protected_role"


class Phase2Action(str, Enum):
    """Phase 2 action enum used for guardrail overrides."""

    TERMINATE = "TERMINATE"
    STOP = "STOP"
    DOWNSIZE = "DOWNSIZE"
    SKIP = "SKIP"
    NEEDS_REVIEW = "NEEDS_REVIEW"


TYPE_A = frozenset({"reads_from", "writes_to", "mounted_to"})
TYPE_B = frozenset({"routes_traffic_to", "load_balances_to"})
TYPE_C = frozenset({"sends_messages_to", "reads_from_queue"})
TYPE_D = frozenset({"sends_logs_to", "monitored_by"})
TYPE_E = frozenset({"replicates_to", "failover_for", "backup_of"})

PROTECTED_ROLES = frozenset({"backup", "dependant_secondary"})
CAPPED_ROLES = frozenset({"dependant_primary"})
STEADY_LIKE_ROLES = frozenset({"steady", "managed"})
TYPE_E_ELIGIBLE_ROLES = frozenset({"steady", "bursty", "managed"})


class Phase2Result(BaseModel):
    model_config = {"use_enum_values": True}

    instance_id: str
    role: str
    waste_type: WasteType
    detection_window: int | None = None
    # NOTE: The waste table uses legacy column names avg_cpu/peak_cpu/avg_ram.
    # These fields hold P95/P99 values. The column names are a DB schema
    # constraint inherited from the original schema and do not reflect the
    # statistical meaning. See writer.py for the explicit mapping.
    p95_cpu: float | None = None
    p99_cpu: float | None = None
    p95_ram: float | None = None
    current_instance_type: str | None = None
    recommended_type: str | None = None
    current_cost_per_hour: float | None = None
    recommended_cost_per_hour: float | None = None
    waste_per_month: float | None = None
    action: Phase2Action
    safety_status: SafetyStatus = SafetyStatus.SAFE
    block_reason: BlockReason | None = None
    fallback_action: Phase2Action | None = None
    pipeline_warning: bool = False
    redundancy_node: bool = False
    depth_of_block: int | None = None
    terraform_block: str | None = None
    fallback_terraform_block: str | None = None
