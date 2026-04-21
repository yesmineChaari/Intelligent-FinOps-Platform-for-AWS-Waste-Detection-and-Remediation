from pydantic import BaseModel
from typing import Optional
from enum import Enum

from .s3_models import S3Rules

# ─── Phase 1 Output Models ────────────────────────────────────────────────────

class WasteAction(str, Enum):
    TERMINATE = "TERMINATE"
    STOP = "STOP"
    DOWNSIZE = "DOWNSIZE"
    REVIEW = "REVIEW"
    SKIP = "SKIP"
    CLEAN = "CLEAN"  # no waste detected

class WasteType(str, Enum):
    ZOMBIE = "zombie"
    STOPPED = "stopped"
    IDLE = "idle"
    OVERSIZED = "oversized"
    TAG_ERROR = "tag_error" # Added for CV failures
    NONE = "none"

class Phase1Result(BaseModel):
    resource_id: int
    resource_name: str
    role: str
    action: WasteAction
    waste_type: WasteType
    detection_window_days: Optional[int] = None
    stopped_days: Optional[int] = None

    # Metrics snapshot
    p95_cpu: Optional[float] = None
    p99_cpu: Optional[float] = None
    max_cpu: Optional[float] = None
    p95_ram: Optional[float] = None
    cv: Optional[float] = None

    # Sizing output
    current_instance_type: Optional[str] = None
    recommended_type: Optional[str] = None
    projected_cpu_pct: Optional[float] = None
    projected_ram_pct: Optional[float] = None
    current_cost_per_hour: Optional[float] = None
    recommended_cost_per_hour: Optional[float] = None
    waste_per_month: Optional[float] = None
    detection_reason: Optional[str] = None


# ─── Rules Models ────────────────────────────────────────────────────────────

class DependantPrimaryRules(BaseModel):
    action: WasteAction
    window_days: int
    idle_p95_cpu_threshold: float
    idle_p95_ram_threshold: float

class BurstyRules(BaseModel):
    action: WasteAction
    window_days: int
    cv_threshold: float
    idle_p99_cpu_threshold: float

class ZombieRules(BaseModel):
    action: WasteAction
    stopped_days_threshold: int

class IdleRules(BaseModel):
    action: WasteAction
    window_days: int
    p95_cpu_threshold: float
    p95_ram_threshold: float
    max_cpu_threshold: float

class OversizedRules(BaseModel):
    action: WasteAction
    window_days: int
    p95_cpu_threshold: float
    p95_ram_threshold: float

class SteadyRules(BaseModel):
    idle: IdleRules
    oversized: OversizedRules

class DetectionRules(BaseModel):
    skipped_roles: list[str]
    zombie: ZombieRules
    dependant_primary: DependantPrimaryRules
    bursty: BurstyRules
    steady: SteadyRules

class SizingRules(BaseModel):
    max_drop_steps: int
    ram_headroom_threshold: float
    cpu_safety_ceiling: float


class Phase2BlastRadiusRules(BaseModel):
    terminate_max_score: int
    stop_max_score: int
    downsize_max_score: int


class Phase2Rules(BaseModel):
    blast_radius: Phase2BlastRadiusRules
    review_label: str
    type_e_relationships: list[str]
    weighted_relationships: dict[str, int]

class Rules(BaseModel):
    detection: DetectionRules
    sizing: SizingRules
    phase2: Phase2Rules
    s3: S3Rules