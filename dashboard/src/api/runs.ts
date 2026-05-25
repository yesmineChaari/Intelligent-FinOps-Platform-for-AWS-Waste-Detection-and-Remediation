import { getJson, resolveMockResponse, USE_MOCKS } from "@/api/client"
import { mockRuns } from "@/mocks/runs"
import type { PipelineRun } from "@/types/runs"

export function getRuns(): Promise<PipelineRun[]> {
  return USE_MOCKS
    ? resolveMockResponse(mockRuns)
    : getJson<PipelineRun[]>("/runs")
}
