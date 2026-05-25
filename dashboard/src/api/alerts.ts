import { resolveMockResponse } from "@/api/client"
import { mockAlerts } from "@/mocks/alerts"
import type { Alert } from "@/types/alerts"

export function getAlerts(): Promise<Alert[]> {
  return resolveMockResponse(mockAlerts)
  // Future FastAPI integration: return getJson<Alert[]>("/alerts")
}
