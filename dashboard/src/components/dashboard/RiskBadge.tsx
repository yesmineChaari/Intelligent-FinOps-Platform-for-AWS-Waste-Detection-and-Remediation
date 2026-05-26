import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

type RiskBadgeProps = {
  risk?: string | null
  className?: string
}

type RiskLevel = "low" | "medium" | "high" | "critical" | "unknown"

const riskStyles: Record<RiskLevel, string> = {
  low: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300",
  medium: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300",
  high: "border-orange-200 bg-orange-50 text-orange-700 dark:border-orange-900 dark:bg-orange-950 dark:text-orange-300",
  critical: "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300",
  unknown: "border-border bg-muted/50 text-muted-foreground",
}

function normalizeRisk(risk?: string | null): RiskLevel {
  const normalized = risk?.trim().toLowerCase().replace(/[\s-]+/g, "_")

  if (
    normalized === "low" ||
    normalized === "medium" ||
    normalized === "high" ||
    normalized === "critical"
  ) {
    return normalized
  }

  return "unknown"
}

function formatRiskLabel(risk: RiskLevel) {
  return `${risk.charAt(0).toUpperCase()}${risk.slice(1)}`
}

export function RiskBadge({ risk, className }: RiskBadgeProps) {
  const normalized = normalizeRisk(risk)

  return (
    <Badge variant="outline" className={cn("font-medium", riskStyles[normalized], className)}>
      {formatRiskLabel(normalized)}
    </Badge>
  )
}
