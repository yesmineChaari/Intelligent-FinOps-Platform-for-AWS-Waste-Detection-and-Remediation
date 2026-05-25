import { resolveMockResponse } from "@/api/client"
import { mockEc2Findings } from "@/mocks/ec2"
import type { Ec2Finding } from "@/types/ec2"

export function getEc2Findings(): Promise<Ec2Finding[]> {
  return resolveMockResponse(mockEc2Findings)
  // Future FastAPI integration: return getJson<Ec2Finding[]>("/ec2/findings")
}
