import { getGuardrailResults } from "@/api/guardrails"
import { PageHeader } from "@/components/page-header"
import { SeverityBadge } from "@/components/severity-badge"
import { StatusBadge } from "@/components/status-badge"
import { TableCard } from "@/components/table-card"
import { TableStateRow } from "@/components/table-state-row"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useApiData } from "@/hooks/use-api-data"

export function GuardrailsPage() {
  const { data, isLoading, error } = useApiData(getGuardrailResults)
  const decisions = data ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        title="Guardrails"
        description="Phase 2 decisions that keep, alter, or block deterministic recommendations before Phase 3."
      />
      <TableCard
        title="Safety decisions"
        description="Guardrails protect sensitive resources and reduce unsafe optimization actions."
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Resource</TableHead>
              <TableHead>Phase 1 original recommendation</TableHead>
              <TableHead>Phase 2 final decision</TableHead>
              <TableHead>Outcome</TableHead>
              <TableHead>Risk level</TableHead>
              <TableHead>Blast radius</TableHead>
              <TableHead>Reason</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableStateRow
              colSpan={7}
              isLoading={isLoading}
              error={error}
              empty={decisions.length === 0}
              emptyMessage="No guardrail decisions available."
            />
            {decisions.map((decision) => (
              <TableRow key={decision.resource}>
                <TableCell className="min-w-56 font-medium">{decision.resource}</TableCell>
                <TableCell className="min-w-60">{decision.originalRecommendation}</TableCell>
                <TableCell className="min-w-60">{decision.finalDecision}</TableCell>
                <TableCell><StatusBadge status={decision.outcome} /></TableCell>
                <TableCell><SeverityBadge level={decision.risk} /></TableCell>
                <TableCell className="min-w-48">{decision.blastRadius}</TableCell>
                <TableCell className="min-w-72 text-muted-foreground">{decision.reason}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableCard>
    </div>
  )
}
