import type { LucideIcon } from "lucide-react"

import { Card, CardContent } from "@/components/ui/card"

type KpiCardProps = {
  label: string
  value: string
  detail: string
  icon: LucideIcon
  tone?: "default" | "positive" | "warning"
}

export function KpiCard({
  label,
  value,
  detail,
  icon: Icon,
  tone = "default",
}: KpiCardProps) {
  const iconStyle = {
    default: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200",
    positive: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
    warning: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  }[tone]

  return (
    <Card className="shadow-xs">
      <CardContent className="flex items-start justify-between gap-4 p-5">
        <div className="min-w-0">
          <p className="text-sm text-muted-foreground">{label}</p>
          <p className="mt-2 text-2xl font-semibold tabular-nums">{value}</p>
          <p className="mt-1 truncate text-xs text-muted-foreground">{detail}</p>
        </div>
        <div className={`rounded-lg p-2.5 ${iconStyle}`}>
          <Icon className="size-5" />
        </div>
      </CardContent>
    </Card>
  )
}
