import { getPhase3Reviews } from "@/api/phase3"
import { Badge } from "@/components/ui/badge"
import { PageHeader } from "@/components/page-header"
import { StatusBadge } from "@/components/status-badge"
import { TableCard } from "@/components/table-card"
import { TableStateRow } from "@/components/table-state-row"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useApiData } from "@/hooks/use-api-data"

export function Phase3ReviewPage() {
  const { data, isLoading, error } = useApiData(getPhase3Reviews)
  const reviews = data ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        title="Phase 3 Review"
        description="Mock LLM verdicts and Terraform generation results produced after deterministic guardrails."
      />
      <TableCard
        title="LLM recommendation review"
        description="Terraform output is surfaced for human verification before any pull request workflow."
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Resource</TableHead>
              <TableHead>LLM verdict</TableHead>
              <TableHead>Final action</TableHead>
              <TableHead>terraform_action</TableHead>
              <TableHead>terraform_block exists</TableHead>
              <TableHead>Parse status</TableHead>
              <TableHead>Explanation preview</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableStateRow
              colSpan={7}
              isLoading={isLoading}
              error={error}
              empty={reviews.length === 0}
              emptyMessage="No Phase 3 reviews available."
            />
            {reviews.map((review) => (
              <TableRow key={review.resource}>
                <TableCell className="min-w-56 font-medium">{review.resource}</TableCell>
                <TableCell>
                  <Badge variant="outline">{review.verdict}</Badge>
                </TableCell>
                <TableCell className="min-w-48">{review.finalAction}</TableCell>
                <TableCell className="font-mono text-xs">{review.terraformAction}</TableCell>
                <TableCell>
                  <StatusBadge status={review.terraformBlock ? "Yes" : "No"} />
                </TableCell>
                <TableCell><StatusBadge status={review.parseStatus} /></TableCell>
                <TableCell className="min-w-80 max-w-md text-muted-foreground">
                  {review.explanation}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableCard>
    </div>
  )
}
