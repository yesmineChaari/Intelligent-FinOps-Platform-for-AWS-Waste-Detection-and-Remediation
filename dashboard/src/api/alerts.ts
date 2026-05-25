import { getJson, resolveMockResponse, USE_MOCKS } from "@/api/client"
import { mockAlerts } from "@/mocks/alerts"
import type { Alert } from "@/types/alerts"

export function getAlerts(): Promise<Alert[]> {
  return USE_MOCKS
    ? resolveMockResponse(mockAlerts)
    : getJson<Alert[]>("/alerts")
}
