import { getEc2Findings } from "@/api/ec2"
import { PageHeader } from "@/components/page-header"
import { SeverityBadge } from "@/components/severity-badge"
import { StatusBadge } from "@/components/status-badge"
import { TableCard } from "@/components/table-card"
import { TableStateRow } from "@/components/table-state-row"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useApiData } from "@/hooks/use-api-data"
import { formatCurrency } from "@/lib/format"

export function Ec2FindingsPage() {
  const { data, isLoading, error } = useApiData(getEc2Findings)
  const findings = data ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        title="EC2 Findings"
        description="EC2 utilization findings produced during Phase 1 and refined for operator review."
        actions={<Button variant="outline">Filter findings</Button>}
      />
      <TableCard
        title={isLoading ? "EC2 instances" : `${findings.length} instances reviewed`}
        description="Sizing and scheduling recommendations include estimated monthly savings before execution."
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Instance ID / name</TableHead>
              <TableHead>Region</TableHead>
              <TableHead>Instance type</TableHead>
              <TableHead>Detected issue</TableHead>
              <TableHead>CPU avg</TableHead>
              <TableHead>CPU p95</TableHead>
              <TableHead>Memory avg</TableHead>
              <TableHead>Recommended action</TableHead>
              <TableHead className="text-right">Monthly saving</TableHead>
              <TableHead>Risk</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableStateRow
              colSpan={11}
              isLoading={isLoading}
              error={error}
              empty={findings.length === 0}
              emptyMessage="No EC2 findings available."
            />
            {findings.map((finding) => (
              <TableRow key={finding.instance}>
                <TableCell className="min-w-56 font-medium">{finding.instance}</TableCell>
                <TableCell>{finding.region}</TableCell>
                <TableCell>{finding.instanceType}</TableCell>
                <TableCell className="min-w-48 text-muted-foreground">{finding.issue}</TableCell>
                <TableCell>{finding.cpuAverage}</TableCell>
                <TableCell>{finding.cpuP95}</TableCell>
                <TableCell>{finding.memoryAverage}</TableCell>
                <TableCell className="min-w-48">{finding.recommendation}</TableCell>
                <TableCell className="text-right font-medium">
                  {formatCurrency(finding.estimatedSaving)}
                </TableCell>
                <TableCell><SeverityBadge level={finding.risk} /></TableCell>
                <TableCell><StatusBadge status={finding.status} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableCard>
    </div>
  )
}
