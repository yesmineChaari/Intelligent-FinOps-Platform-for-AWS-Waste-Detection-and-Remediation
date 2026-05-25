from typing import Literal

from pydantic import BaseModel


class GuardrailDecisionResponse(BaseModel):
    resource: str
    originalRecommendation: str
    finalDecision: str
    outcome: Literal["Kept", "Changed", "Blocked"]
    risk: Literal["Low", "Medium", "High", "Critical"]
    blastRadius: str
    reason: str
