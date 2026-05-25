import type { S3Finding } from "@/types/s3"

export const mockS3Findings: S3Finding[] = [
  {
    bucket: "pfa-prod-cloudtrail-archive",
    region: "us-east-1",
    issue: "Stale audit archive",
    storageClass: "STANDARD",
    footprint: "9.8 TB / 8.4M objects",
    lifecycleAction: "Transition to Glacier Instant Retrieval after 90 days",
    estimatedSaving: 184,
    status: "Ready for review",
  },
  {
    bucket: "analytics-raw-events",
    region: "eu-west-1",
    issue: "Infrequent historical access",
    storageClass: "STANDARD",
    footprint: "26.1 TB / 14.1M objects",
    lifecycleAction: "Transition to Intelligent-Tiering",
    estimatedSaving: 292,
    status: "Approved",
  },
  {
    bucket: "terraform-state-prod",
    region: "us-east-1",
    issue: "Protected state bucket",
    storageClass: "STANDARD",
    footprint: "640 MB / 2.4K objects",
    lifecycleAction: "No action - excluded by guardrail",
    estimatedSaving: 0,
    status: "Blocked",
  },
  {
    bucket: "image-derivatives-old",
    region: "us-west-2",
    issue: "Abandoned generated assets",
    storageClass: "STANDARD_IA",
    footprint: "4.2 TB / 1.1M objects",
    lifecycleAction: "Expire after 365 days",
    estimatedSaving: 73,
    status: "Pending owner",
  },
]
