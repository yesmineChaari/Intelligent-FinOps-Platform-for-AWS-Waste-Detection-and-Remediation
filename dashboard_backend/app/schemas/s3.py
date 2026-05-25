from pydantic import BaseModel


class S3FindingResponse(BaseModel):
    bucket: str
    region: str
    issue: str
    storageClass: str
    footprint: str
    lifecycleAction: str
    estimatedSaving: float
    status: str
