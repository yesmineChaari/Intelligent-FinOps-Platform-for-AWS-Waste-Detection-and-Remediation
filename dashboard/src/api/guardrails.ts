import { resolveMockResponse } from "@/api/client"
import { mockGuardrailResults } from "@/mocks/guardrails"
import type { GuardrailDecision } from "@/types/guardrails"

export function getGuardrailResults(): Promise<GuardrailDecision[]> {
  return resolveMockResponse(mockGuardrailResults)
  // Future FastAPI integration: return getJson<GuardrailDecision[]>("/guardrails")
}
