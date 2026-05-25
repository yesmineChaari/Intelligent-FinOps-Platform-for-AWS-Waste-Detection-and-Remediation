from pydantic import BaseModel


class Phase3ReviewResponse(BaseModel):
    resource: str
    verdict: str
    finalAction: str
    terraformAction: str
    terraformBlock: bool
    parseStatus: str
    explanation: str
