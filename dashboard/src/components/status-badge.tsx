import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

type StatusBadgeProps = {
  status: string
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const normalized = status.toLowerCase()
  const style = normalized.includes("block") || normalized.includes("fail")
    ? "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
    : normalized.includes("warning") || normalized.includes("pending") || normalized.includes("review")
      ? "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300"
      : normalized.includes("complete") || normalized.includes("approved") || normalized.includes("resolved") || normalized.includes("parsed")
        ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300"
        : "border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300"

  return (
    <Badge variant="outline" className={cn("font-medium", style)}>
      {status}
    </Badge>
  )
}
