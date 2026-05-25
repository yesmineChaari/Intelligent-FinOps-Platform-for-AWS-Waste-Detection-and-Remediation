import { resolveMockResponse } from "@/api/client"
import { mockPhase3Reviews } from "@/mocks/phase3"
import type { Phase3Review } from "@/types/phase3"

export function getPhase3Reviews(): Promise<Phase3Review[]> {
  return resolveMockResponse(mockPhase3Reviews)
  // Future FastAPI integration: return getJson<Phase3Review[]>("/phase3/reviews")
}
