export const pageIds = [
  "overview",
  "ec2-findings",
  "s3-findings",
  "guardrails",
  "phase3-review",
  "alerts",
  "runs-history",
] as const

export type PageId = (typeof pageIds)[number]

export const pageMeta: Record<
  PageId,
  { title: string; description: string }
> = {
  overview: {
    title: "Overview",
    description: "Optimization posture and estimated savings across the latest pipeline run.",
  },
  "ec2-findings": {
    title: "EC2 Findings",
    description: "Rightsizing and lifecycle findings detected from EC2 utilization signals.",
  },
  "s3-findings": {
    title: "S3 Findings",
    description: "Storage waste and lifecycle optimization opportunities by bucket.",
  },
  guardrails: {
    title: "Guardrails",
    description: "Phase 2 safety decisions applied to Phase 1 recommendations.",
  },
  "phase3-review": {
    title: "Phase 3 Review",
    description: "LLM review results and Terraform action readiness.",
  },
  alerts: {
    title: "Alerts",
    description: "Operational notifications and items requiring review.",
  },
  "runs-history": {
    title: "Runs History",
    description: "Past pipeline executions, outputs, status, and realized opportunity size.",
  },
}

export function pageFromHash(hash: string): PageId {
  const value = hash.replace(/^#\/?/, "")
  return pageIds.includes(value as PageId) ? (value as PageId) : "overview"
}
