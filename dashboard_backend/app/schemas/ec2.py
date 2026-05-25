from typing import Literal

from pydantic import BaseModel


class Ec2FindingResponse(BaseModel):
    instance: str
    region: str
    instanceType: str
    issue: str
    cpuAverage: str
    cpuP95: str
    memoryAverage: str
    recommendation: str
    estimatedSaving: float
    risk: Literal["Low", "Medium", "High", "Critical"]
    status: str
