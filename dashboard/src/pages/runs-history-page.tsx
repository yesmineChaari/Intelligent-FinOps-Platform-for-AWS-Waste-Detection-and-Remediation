import { getRuns } from "@/api/runs"
import { PageHeader } from "@/components/page-header"
import { StatusBadge } from "@/components/status-badge"
import { TableCard } from "@/components/table-card"
import { TableStateRow } from "@/components/table-state-row"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useApiData } from "@/hooks/use-api-data"
import { formatCurrency } from "@/lib/format"

export function RunsHistoryPage() {
  const { data, isLoading, error } = useApiData(getRuns)
  const runs = data ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        title="Runs History"
        description="Optimization pipeline execution history across deterministic and Phase 3 processing."
      />
      <TableCard
        title="Optimization runs"
        description="Statuses represent the pipeline checkpoints exposed by the containerized workflow."
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Run ID</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Started at</TableHead>
              <TableHead>Completed at</TableHead>
              <TableHead>Duration</TableHead>
              <TableHead className="text-right">EC2 findings</TableHead>
              <TableHead className="text-right">S3 findings</TableHead>
              <TableHead className="text-right">Blocked recommendations</TableHead>
              <TableHead className="text-right">Phase 3 parse errors</TableHead>
              <TableHead className="text-right">Total savings</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableStateRow
              colSpan={10}
              isLoading={isLoading}
              error={error}
              empty={runs.length === 0}
              emptyMessage="No optimization runs available."
            />
            {runs.map((run) => (
              <TableRow key={run.runId}>
                <TableCell className="font-medium">{run.runId}</TableCell>
                <TableCell><StatusBadge status={run.status} /></TableCell>
                <TableCell>{run.startedAt}</TableCell>
                <TableCell>{run.completedAt}</TableCell>
                <TableCell>{run.duration}</TableCell>
                <TableCell className="text-right">{run.ec2Findings}</TableCell>
                <TableCell className="text-right">{run.s3Findings}</TableCell>
                <TableCell className="text-right">{run.blocked}</TableCell>
                <TableCell className="text-right">{run.phase3ParseErrors}</TableCell>
                <TableCell className="text-right font-medium">
                  {formatCurrency(run.totalSavings)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableCard>
    </div>
  )
}
