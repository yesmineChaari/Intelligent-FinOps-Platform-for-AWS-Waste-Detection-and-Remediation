import { useId, useState, type ReactNode } from "react"
import { ChevronDownIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { cn } from "@/lib/utils"

type RawDetailsToggleProps = {
  title?: string
  description?: ReactNode
  children: ReactNode
  defaultOpen?: boolean
  className?: string
}

export function RawDetailsToggle({
  title = "Raw details",
  description,
  children,
  defaultOpen = false,
  className,
}: RawDetailsToggleProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen)
  const detailsId = useId()

  return (
    <Card className={cn("gap-0 py-0 shadow-xs", className)}>
      <CardHeader className="py-4">
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
        <CardAction>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-controls={detailsId}
            aria-expanded={isOpen}
            onClick={() => setIsOpen((open) => !open)}
          >
            {isOpen ? "Collapse details" : "Expand details"}
            <ChevronDownIcon
              className={cn("transition-transform", isOpen && "rotate-180")}
              aria-hidden="true"
            />
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent id={detailsId} hidden={!isOpen} className="border-t py-4">
        {children}
      </CardContent>
    </Card>
  )
}
