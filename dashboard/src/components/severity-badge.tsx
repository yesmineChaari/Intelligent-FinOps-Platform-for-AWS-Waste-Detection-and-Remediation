import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

type SeverityBadgeProps = {
  level: "Info" | "Low" | "Warning" | "Medium" | "High" | "Critical"
}

export function SeverityBadge({ level }: SeverityBadgeProps) {
  const style = {
    Info: "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-300",
    Low: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300",
    Warning: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300",
    Medium: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300",
    High: "border-orange-200 bg-orange-50 text-orange-700 dark:border-orange-900 dark:bg-orange-950 dark:text-orange-300",
    Critical: "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300",
  }[level]

  return (
    <Badge variant="outline" className={cn("font-medium", style)}>
      {level}
    </Badge>
  )
}
