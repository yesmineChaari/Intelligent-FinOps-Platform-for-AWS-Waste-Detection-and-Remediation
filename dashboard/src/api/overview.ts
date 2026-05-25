import { getJson, resolveMockResponse, USE_MOCKS } from "@/api/client"
import { mockOverview } from "@/mocks/overview"
import type { Overview } from "@/types/overview"

export function getOverview(): Promise<Overview> {
  return USE_MOCKS
    ? resolveMockResponse(mockOverview)
    : getJson<Overview>("/overview")
}
