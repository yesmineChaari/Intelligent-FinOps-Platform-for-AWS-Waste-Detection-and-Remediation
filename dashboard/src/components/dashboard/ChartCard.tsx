import type { ReactNode } from "react"

import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { cn } from "@/lib/utils"

type ChartCardProps = {
  title: string
  description?: ReactNode
  children: ReactNode
  footer?: ReactNode
  className?: string
}

export function ChartCard({
  title,
  description,
  children,
  footer,
  className,
}: ChartCardProps) {
  return (
    <Card className={cn("shadow-xs", className)}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent className="h-[280px]">{children}</CardContent>
      {footer && <CardFooter className="text-sm text-muted-foreground">{footer}</CardFooter>}
    </Card>
  )
}
