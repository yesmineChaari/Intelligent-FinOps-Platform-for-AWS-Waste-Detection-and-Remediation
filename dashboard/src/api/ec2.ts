import { getJson, resolveMockResponse, USE_MOCKS } from "@/api/client"
import { mockEc2Findings } from "@/mocks/ec2"
import type { Ec2Finding } from "@/types/ec2"

export function getEc2Findings(): Promise<Ec2Finding[]> {
  return USE_MOCKS
    ? resolveMockResponse(mockEc2Findings)
    : getJson<Ec2Finding[]>("/ec2/findings")
}
