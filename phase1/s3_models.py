"""
S3 Phase 1 models.
Mirrors the same pattern as EC2 Phase 1 result models and rules.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class S3WasteType(str, Enum):
    MISSING_LIFECYCLE = "missing_lifecycle"
    ABANDONED = "abandoned"
    STORAGE_MISMATCH = "storage_mismatch"
    NONE = "none"


class S3Action(str, Enum):
    RECOMMEND_LIFECYCLE = "RECOMMEND_LIFECYCLE"
    REVIEW = "REVIEW"
    CLEAN = "CLEAN"


class S3FindingResult(BaseModel):
    bucket_name: str

    action: S3Action
    waste_type: S3WasteType
    detection_window: Optional[str] = None

    has_lifecycle: Optional[bool] = None

    total_requests_30d: Optional[float] = None
    object_count: Optional[int] = None

    pct_older_90_days: Optional[float] = None
    estimated_monthly_savings: Optional[float] = None

    recommended_action: Optional[str] = None
    lifecycle_policy_json: Optional[dict] = None

    detection_reason: Optional[str] = None


class S3AbandonedRules(BaseModel):
    window_days: int
    min_object_count: int
    max_total_requests: float


class S3StorageMismatchRules(BaseModel):
    window_days: int
    pct_older_90_days_threshold: float
    min_pct_in_standard: float
    standard_price_per_gb: float
    glacier_price_per_gb: float


class S3Rules(BaseModel):
    abandoned: S3AbandonedRules
    storage_mismatch: S3StorageMismatchRules
