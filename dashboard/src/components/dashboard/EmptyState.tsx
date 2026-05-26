import type { ReactNode } from "react"

import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"

type EmptyStateProps = {
  title: string
  description?: ReactNode
  icon?: ReactNode
  action?: ReactNode
  className?: string
}

export function EmptyState({
  title,
  description,
  icon,
  action,
  className,
}: EmptyStateProps) {
  return (
    <Card className={cn("border border-dashed border-border shadow-none ring-0", className)}>
      <CardContent className="flex min-h-40 flex-col items-center justify-center px-6 py-10 text-center">
        {icon && (
          <div className="mb-4 rounded-full bg-muted p-3 text-muted-foreground [&_svg]:size-5">
            {icon}
          </div>
        )}
        <h3 className="text-base font-medium">{title}</h3>
        {description && (
          <div className="mt-1 max-w-md text-sm text-muted-foreground">{description}</div>
        )}
        {action && <div className="mt-5">{action}</div>}
      </CardContent>
    </Card>
  )
}
