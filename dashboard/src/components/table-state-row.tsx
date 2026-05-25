import { TableCell, TableRow } from "@/components/ui/table"

type TableStateRowProps = {
  colSpan: number
  isLoading: boolean
  error: string | null
  empty: boolean
  emptyMessage?: string
}

export function TableStateRow({
  colSpan,
  isLoading,
  error,
  empty,
  emptyMessage = "No records available.",
}: TableStateRowProps) {
  if (!isLoading && !error && !empty) {
    return null
  }

  const message = isLoading ? "Loading mock data..." : error ?? emptyMessage

  return (
    <TableRow>
      <TableCell colSpan={colSpan} className="h-24 text-center text-muted-foreground">
        {message}
      </TableCell>
    </TableRow>
  )
}
