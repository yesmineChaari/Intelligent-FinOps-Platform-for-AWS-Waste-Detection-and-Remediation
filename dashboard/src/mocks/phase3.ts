import type { Phase3Review } from "@/types/phase3"

export const mockPhase3Reviews: Phase3Review[] = [
  {
    resource: "analytics-etl-01 / i-02e4b26ba8",
    verdict: "AGENT_VALIDATED",
    finalAction: "Resize instance",
    terraformAction: "update_instance_type",
    terraformBlock: true,
    parseStatus: "Parsed",
    explanation: "The recommendation reduces spend while preserving observed ETL headroom.",
  },
  {
    resource: "batch-worker-04 / i-0812bb2cd1",
    verdict: "AGENT_VALIDATED",
    finalAction: "Apply schedule",
    terraformAction: "add_scheduler_tags",
    terraformBlock: true,
    parseStatus: "Parsed",
    explanation: "A scheduled operating window avoids resizing risk during batch peaks.",
  },
  {
    resource: "pfa-prod-cloudtrail-archive",
    verdict: "LLM_GENERATED",
    finalAction: "Add lifecycle transition",
    terraformAction: "add_s3_lifecycle_rule",
    terraformBlock: true,
    parseStatus: "Parsed",
    explanation: "Archive objects are retained while lower-cost storage reduces long-term cost.",
  },
  {
    resource: "image-derivatives-old",
    verdict: "REVIEW_REQUIRED",
    finalAction: "Confirm retention ownership",
    terraformAction: "none",
    terraformBlock: false,
    parseStatus: "Needs review",
    explanation: "Deletion could be appropriate, but product ownership is not established.",
  },
]
