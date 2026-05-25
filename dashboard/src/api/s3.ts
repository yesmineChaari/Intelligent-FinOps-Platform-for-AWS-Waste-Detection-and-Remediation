import { getJson, resolveMockResponse, USE_MOCKS } from "@/api/client"
import { mockS3Findings } from "@/mocks/s3"
import type { S3Finding } from "@/types/s3"

export function getS3Findings(): Promise<S3Finding[]> {
  return USE_MOCKS
    ? resolveMockResponse(mockS3Findings)
    : getJson<S3Finding[]>("/s3/findings")
}
