from pydantic import AliasChoices, BaseModel, Field

from agent1.phase1.models import WasteAction, WasteType


class RelationshipEdge(BaseModel):
    resource_id: int
    related_resource_id: int
    relationship_type: str
    related_resource_type: str | None = None


class Phase2Result(BaseModel):
    model_config = {"use_enum_values": True, "populate_by_name": True}

    resource_id: int
    instance_name: str = Field(validation_alias=AliasChoices("instance_name", "resource_name"))
    role: str
    waste_type: WasteType
    phase1_action: WasteAction
    action: WasteAction = Field(validation_alias=AliasChoices("phase2_action", "action"))
    detection_reason: str | None = None

    phase2_action_changed: bool = False
    phase2_action_reason: str | None = None
    phase2_decision_details: str | None = None
    blast_radius_explanation: str | None = None

    blast_radius: int = Field(default=0, validation_alias=AliasChoices("blast_radius", "blast_radius_score"))
    relationship_count: int = 0
    skip_write: bool = False
    block_reason: str | None = Field(default=None, validation_alias=AliasChoices("block_reason", "guardrail_reason"))

    detection_window_days: int | None = None
    stopped_days: int | None = None
    instance_type: str | None = Field(
        default=None,
        validation_alias=AliasChoices("instance_type", "current_instance_type"),
    )
    recommended_type: str | None = None
    current_cost_per_hour: float | None = None
    recommended_cost_per_hour: float | None = None
    waste_per_month: float | None = None

    @property
    def resource_name(self) -> str:
        return self.instance_name

    @property
    def phase2_action(self) -> WasteAction:
        return self.action

    @property
    def blast_radius_score(self) -> int:
        return self.blast_radius

    @property
    def guardrail_reason(self) -> str | None:
        return self.block_reason

    @property
    def current_instance_type(self) -> str | None:
        return self.instance_type
