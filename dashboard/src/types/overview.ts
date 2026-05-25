import type { Alert } from "@/types/alerts"

export type SavingsTrendPoint = {
  month: string
  savings: number
}

export type FindingTypeCount = {
  type: string
  count: number
}

export type LatestRunSummary = {
  runId: string
  status: string
  duration: string
}

export type Overview = {
  totalEstimatedMonthlySavings: number
  ec2FindingsCount: number
  s3FindingsCount: number
  blockedRiskyRecommendationsCount: number
  latestRun: LatestRunSummary
  savingsTrend: SavingsTrendPoint[]
  findingsByType: FindingTypeCount[]
  recentAlerts: Alert[]
}
