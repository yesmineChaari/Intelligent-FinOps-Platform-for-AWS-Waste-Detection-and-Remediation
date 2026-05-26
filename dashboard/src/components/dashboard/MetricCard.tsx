import type { ReactNode } from "react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"

export type MetricCardVariant = "default" | "success" | "warning" | "danger" | "info"

type MetricCardProps = {
  title: string
  value: ReactNode
  subtitle?: ReactNode
  icon?: ReactNode
  trendLabel?: ReactNode
  variant?: MetricCardVariant
}

const variantStyles: Record<
  MetricCardVariant,
  { card: string; icon: string; trend: string }
> = {
  default: {
    card: "",
    icon: "bg-muted text-muted-foreground",
    trend: "border-border bg-muted/40 text-foreground",
  },
  success: {
    card: "ring-emerald-200/70 dark:ring-emerald-900/70",
    icon: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
    trend: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300",
  },
  warning: {
    card: "ring-amber-200/70 dark:ring-amber-900/70",
    icon: "bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
    trend: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300",
  },
  danger: {
    card: "ring-red-200/70 dark:ring-red-900/70",
    icon: "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300",
    trend: "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300",
  },
  info: {
    card: "ring-blue-200/70 dark:ring-blue-900/70",
    icon: "bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300",
    trend: "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-300",
  },
}

export function MetricCard({
  title,
  value,
  subtitle,
  icon,
  trendLabel,
  variant = "default",
}: MetricCardProps) {
  const styles = variantStyles[variant]

  return (
    <Card className={cn("shadow-xs", styles.card)}>
      <CardContent className="flex items-start justify-between gap-4 p-5">
        <div className="min-w-0 flex-1">
          <p className="text-sm text-muted-foreground">{title}</p>
          <div className="mt-2 text-2xl font-semibold tracking-tight tabular-nums">
            {value}
          </div>
          {(subtitle || trendLabel) && (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {subtitle && <div className="text-xs text-muted-foreground">{subtitle}</div>}
              {trendLabel && (
                <Badge variant="outline" className={cn("font-medium", styles.trend)}>
                  {trendLabel}
                </Badge>
              )}
            </div>
          )}
        </div>
        {icon && (
          <div className={cn("shrink-0 rounded-lg p-2.5 [&_svg]:size-5", styles.icon)}>
            {icon}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
