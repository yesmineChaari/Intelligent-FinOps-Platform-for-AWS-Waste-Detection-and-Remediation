import { mockAlerts } from "@/mocks/alerts"
import type { Overview } from "@/types/overview"

export const mockOverview: Overview = {
  totalEstimatedMonthlySavings: 1829,
  ec2FindingsCount: 5,
  s3FindingsCount: 4,
  blockedRiskyRecommendationsCount: 2,
  latestRun: {
    runId: "RUN-1042",
    status: "Completed",
    duration: "20m 11s",
  },
  savingsTrend: [
    { month: "Dec", savings: 960 },
    { month: "Jan", savings: 1110 },
    { month: "Feb", savings: 1280 },
    { month: "Mar", savings: 1435 },
    { month: "Apr", savings: 1670 },
    { month: "May", savings: 1829 },
  ],
  findingsByType: [
    { type: "EC2 Resize", count: 3 },
    { type: "EC2 Schedule", count: 1 },
    { type: "EC2 Retire", count: 1 },
    { type: "S3 Lifecycle", count: 3 },
    { type: "S3 Protected", count: 1 },
  ],
  recentAlerts: mockAlerts,
}
