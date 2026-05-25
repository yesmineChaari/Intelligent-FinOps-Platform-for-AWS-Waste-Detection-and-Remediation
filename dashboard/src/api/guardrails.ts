import { getJson, resolveMockResponse, USE_MOCKS } from "@/api/client"
import { mockGuardrailResults } from "@/mocks/guardrails"
import type { GuardrailDecision } from "@/types/guardrails"

export function getGuardrailResults(): Promise<GuardrailDecision[]> {
  return USE_MOCKS
    ? resolveMockResponse(mockGuardrailResults)
    : getJson<GuardrailDecision[]>("/guardrails")
}
