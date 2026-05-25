import { resolveMockResponse } from "@/api/client"
import { mockOverview } from "@/mocks/overview"
import type { Overview } from "@/types/overview"

export function getOverview(): Promise<Overview> {
  return resolveMockResponse(mockOverview)
  // Future FastAPI integration: return getJson<Overview>("/overview")
}
