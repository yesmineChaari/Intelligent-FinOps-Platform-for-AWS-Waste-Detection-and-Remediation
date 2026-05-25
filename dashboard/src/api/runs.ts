import { resolveMockResponse } from "@/api/client"
import { mockRuns } from "@/mocks/runs"
import type { PipelineRun } from "@/types/runs"

export function getRuns(): Promise<PipelineRun[]> {
  return resolveMockResponse(mockRuns)
  // Future FastAPI integration: return getJson<PipelineRun[]>("/runs")
}
