import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

type StatusBadgeProps = {
  status?: string | null
  label?: string
  className?: string
}

type StatusTone = "neutral" | "success" | "warning" | "danger" | "info"

const statusTones: Record<string, StatusTone> = {
  approved: "success",
  closed: "success",
  completed: "success",
  kept: "success",
  parse_ok: "success",
  recommended: "success",
  resolved: "success",
  allowed: "success",
  open: "info",
  running: "info",
  changed: "warning",
  pending: "warning",
  review: "warning",
  blocked: "danger",
  failed: "danger",
  parse_error: "danger",
}

const toneStyles: Record<StatusTone, string> = {
  neutral: "border-border bg-muted/50 text-muted-foreground",
  success: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300",
  warning: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300",
  danger: "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300",
  info: "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-300",
}

function normalizeStatus(status?: string | null) {
  return (
    status
      ?.trim()
      .toLowerCase()
      .replace(/[\s-]+/g, "_")
      .replace(/^_+|_+$/g, "") || "unknown"
  )
}

function formatStatusLabel(status: string) {
  return status
    .split("_")
    .filter(Boolean)
    .map((word) => `${word.charAt(0).toUpperCase()}${word.slice(1)}`)
    .join(" ")
}

export function StatusBadge({ status, label, className }: StatusBadgeProps) {
  const normalized = normalizeStatus(status)
  const tone = statusTones[normalized] ?? "neutral"

  return (
    <Badge variant="outline" className={cn("font-medium", toneStyles[tone], className)}>
      {label ?? formatStatusLabel(normalized)}
    </Badge>
  )
}
