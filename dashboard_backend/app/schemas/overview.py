from pydantic import BaseModel

from .alerts import AlertResponse


class SavingsTrendPointResponse(BaseModel):
    month: str
    savings: float


class FindingTypeCountResponse(BaseModel):
    type: str
    count: int


class LatestRunSummaryResponse(BaseModel):
    runId: str
    status: str
    duration: str


class OverviewResponse(BaseModel):
    totalEstimatedMonthlySavings: float
    ec2FindingsCount: int
    s3FindingsCount: int
    blockedRiskyRecommendationsCount: int
    latestRun: LatestRunSummaryResponse
    savingsTrend: list[SavingsTrendPointResponse]
    findingsByType: list[FindingTypeCountResponse]
    recentAlerts: list[AlertResponse]
