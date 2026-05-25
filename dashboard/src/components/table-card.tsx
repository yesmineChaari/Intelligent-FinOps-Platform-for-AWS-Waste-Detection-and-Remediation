import type { ReactNode } from "react"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

type TableCardProps = {
  title?: string
  description?: string
  children: ReactNode
}

export function TableCard({ title, description, children }: TableCardProps) {
  return (
    <Card className="overflow-hidden shadow-xs">
      {title && (
        <CardHeader>
          <CardTitle>{title}</CardTitle>
          {description && <CardDescription>{description}</CardDescription>}
        </CardHeader>
      )}
      <CardContent className="overflow-x-auto p-0">{children}</CardContent>
    </Card>
  )
}
