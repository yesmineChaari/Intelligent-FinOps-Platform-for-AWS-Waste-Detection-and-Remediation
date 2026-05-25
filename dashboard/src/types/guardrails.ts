import type { RiskLevel } from "@/types/ec2"

export type GuardrailDecision = {
  resource: string
  originalRecommendation: string
  finalDecision: string
  outcome: "Kept" | "Changed" | "Blocked"
  risk: RiskLevel
  blastRadius: string
  reason: string
}
