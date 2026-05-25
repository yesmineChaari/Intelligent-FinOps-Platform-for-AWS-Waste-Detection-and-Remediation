import type { Alert } from "@/types/alerts"

export const mockAlerts: Alert[] = [
  {
    severity: "Critical",
    type: "Guardrail block",
    message: "Resize prevented for memory-sensitive production instance.",
    resource: "payments-primary",
    status: "Open",
    createdAt: "Today, 09:14",
  },
  {
    severity: "High",
    type: "Terraform review",
    message: "Lifecycle delete action requires an owner confirmation.",
    resource: "image-derivatives-old",
    status: "Investigating",
    createdAt: "Today, 08:42",
  },
  {
    severity: "Warning",
    type: "Phase 3 parse",
    message: "One recommendation returned without a Terraform block.",
    resource: "run-1041",
    status: "Open",
    createdAt: "Yesterday, 17:06",
  },
  {
    severity: "Info",
    type: "Optimization run",
    message: "Latest Phase 3 evaluation completed successfully.",
    resource: "run-1042",
    status: "Resolved",
    createdAt: "Today, 09:22",
  },
]
