import type { GuardrailDecision } from "@/types/guardrails"

export const mockGuardrailResults: GuardrailDecision[] = [
  {
    resource: "payments-primary / i-073a9d291f",
    originalRecommendation: "Resize r6i.xlarge to r6i.large",
    finalDecision: "No change permitted",
    outcome: "Blocked",
    risk: "Critical",
    blastRadius: "Tier-0 payment traffic",
    reason: "High memory utilization and primary workload tag.",
  },
  {
    resource: "batch-worker-04 / i-0812bb2cd1",
    originalRecommendation: "Resize c6i.4xlarge to c6i.large",
    finalDecision: "Schedule stop/start outside batch window",
    outcome: "Changed",
    risk: "Low",
    blastRadius: "Nightly batch job",
    reason: "High p95 CPU makes resizing unsafe; scheduling preserves capacity.",
  },
  {
    resource: "analytics-etl-01 / i-02e4b26ba8",
    originalRecommendation: "Resize m5.4xlarge to m6i.xlarge",
    finalDecision: "Resize m5.4xlarge to m6i.xlarge",
    outcome: "Kept",
    risk: "Medium",
    blastRadius: "ETL processing window",
    reason: "Utilization thresholds remain below sizing policy limits.",
  },
  {
    resource: "terraform-state-prod",
    originalRecommendation: "Move objects to Glacier",
    finalDecision: "Retain current lifecycle",
    outcome: "Blocked",
    risk: "High",
    blastRadius: "Infrastructure deployment recovery",
    reason: "State and lock artifacts are excluded from automated lifecycle action.",
  },
]
