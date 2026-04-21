from pydantic import BaseModel
from typing import Optional
from enum import Enum

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

# ─── S3 Output Models ───────────────────────────────────────────────────────

class S3Action(str, Enum):
    RECOMMEND_LIFECYCLE = "RECOMMEND_LIFECYCLE"
    REVIEW = "REVIEW"
    CLEAN = "CLEAN"


class S3WasteType(str, Enum):
    MISSING_LIFECYCLE = "missing_lifecycle"
    ABANDONED = "abandoned"
    STORAGE_MISMATCH = "storage_mismatch"


class S3FindingResult(BaseModel):
    bucket_name: str
    action: S3Action
    waste_type: S3WasteType

    detection_window: Optional[str] = None
    has_lifecycle: Optional[bool] = None
    object_count: Optional[int] = None
    total_requests_30d: Optional[float] = None
    pct_older_90_days: Optional[float] = None
    estimated_monthly_savings: Optional[float] = None

    recommended_action: Optional[str] = None
    lifecycle_policy_json: Optional[dict] = None
    detection_reason: Optional[str] = None


# ─── S3 Rules Models ────────────────────────────────────────────────────────

class S3AbandonedRules(BaseModel):
    window_days: int
    min_object_count: int
    max_total_requests: int


class S3StorageMismatchRules(BaseModel):
    window_days: int
    pct_older_90_days_threshold: float
    min_pct_in_standard: float
    standard_price_per_gb: float
    glacier_price_per_gb: float


class S3Rules(BaseModel):
    abandoned: S3AbandonedRules
    storage_mismatch: S3StorageMismatchRules


class Rules(BaseModel):
    detection: DetectionRules
    sizing: SizingRules
    phase2: Phase2Rules
    s3: S3Rules