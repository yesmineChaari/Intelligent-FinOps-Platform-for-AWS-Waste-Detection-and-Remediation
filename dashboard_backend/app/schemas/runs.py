from pydantic import BaseModel


class RunResponse(BaseModel):
    runId: str
    status: str
    startedAt: str
    completedAt: str
    duration: str
    ec2Findings: int
    s3Findings: int
    blocked: int
    phase3ParseErrors: int
    totalSavings: float
