from typing import Literal

from pydantic import BaseModel


class AlertResponse(BaseModel):
    severity: Literal["Info", "Warning", "High", "Critical"]
    type: str
    message: str
    resource: str
    status: str
    createdAt: str
