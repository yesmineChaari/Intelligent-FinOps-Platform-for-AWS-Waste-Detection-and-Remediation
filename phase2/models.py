from pydantic import BaseModel

from phase1.models import WasteAction, WasteType


class RelationshipEdge(BaseModel):
    resource_id: int
    related_resource_id: int
    relationship_type: str
    related_resource_type: str | None = None


class Phase2Result(BaseModel):
    model_config = {"use_enum_values": True}

    resource_id: int
    resource_name: str
    role: str
    waste_type: WasteType
    phase1_action: WasteAction
    action: WasteAction
    detection_reason: str | None = None

    phase2_action: WasteAction
    phase2_action_changed: bool = False
    phase2_action_reason: str | None = None
    phase2_decision_details: str | None = None
    blast_radius_explanation: str | None = None

    blast_radius_score: int = 0
    relationship_count: int = 0
    skip_write: bool = False
    guardrail_reason: str | None = None

    detection_window_days: int | None = None
    stopped_days: int | None = None
    current_instance_type: str | None = None
    recommended_type: str | None = None
    current_cost_per_hour: float | None = None
    recommended_cost_per_hour: float | None = None
    waste_per_month: float | None = None
