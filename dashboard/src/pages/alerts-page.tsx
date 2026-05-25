import { getAlerts } from "@/api/alerts"
import { PageHeader } from "@/components/page-header"
import { SeverityBadge } from "@/components/severity-badge"
import { StatusBadge } from "@/components/status-badge"
import { TableCard } from "@/components/table-card"
import { TableStateRow } from "@/components/table-state-row"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useApiData } from "@/hooks/use-api-data"

export function AlertsPage() {
  const { data, isLoading, error } = useApiData(getAlerts)
  const alerts = data ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        title="Alerts"
        description="Mock safety, parsing, and run notifications needing operator awareness."
        actions={<Button variant="outline">Mark all reviewed</Button>}
      />
      <TableCard title="Active and recent alerts">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Severity</TableHead>
              <TableHead>Alert type</TableHead>
              <TableHead>Message</TableHead>
              <TableHead>Related resource</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Created time</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableStateRow
              colSpan={6}
              isLoading={isLoading}
              error={error}
              empty={alerts.length === 0}
              emptyMessage="No alerts available."
            />
            {alerts.map((alert) => (
              <TableRow key={`${alert.type}-${alert.resource}`}>
                <TableCell><SeverityBadge level={alert.severity} /></TableCell>
                <TableCell className="font-medium">{alert.type}</TableCell>
                <TableCell className="min-w-96">{alert.message}</TableCell>
                <TableCell>{alert.resource}</TableCell>
                <TableCell><StatusBadge status={alert.status} /></TableCell>
                <TableCell className="text-muted-foreground">{alert.createdAt}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableCard>
    </div>
  )
}
