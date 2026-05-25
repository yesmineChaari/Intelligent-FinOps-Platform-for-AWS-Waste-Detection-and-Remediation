import { getS3Findings } from "@/api/s3"
import { PageHeader } from "@/components/page-header"
import { StatusBadge } from "@/components/status-badge"
import { TableCard } from "@/components/table-card"
import { TableStateRow } from "@/components/table-state-row"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useApiData } from "@/hooks/use-api-data"
import { formatCurrency } from "@/lib/format"

export function S3FindingsPage() {
  const { data, isLoading, error } = useApiData(getS3Findings)
  const findings = data ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        title="S3 Findings"
        description="S3 lifecycle findings for retained, infrequently accessed, and protected objects."
        actions={<Button variant="outline">Export lifecycle plan</Button>}
      />
      <TableCard
        title={isLoading ? "S3 buckets" : `${findings.length} buckets analyzed`}
        description="Lifecycle suggestions are reviewed before policy or Terraform changes are generated."
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Bucket name</TableHead>
              <TableHead>Region</TableHead>
              <TableHead>Detected issue</TableHead>
              <TableHead>Storage class</TableHead>
              <TableHead>Objects / estimated size</TableHead>
              <TableHead>Suggested lifecycle action</TableHead>
              <TableHead className="text-right">Monthly saving</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableStateRow
              colSpan={8}
              isLoading={isLoading}
              error={error}
              empty={findings.length === 0}
              emptyMessage="No S3 findings available."
            />
            {findings.map((finding) => (
              <TableRow key={finding.bucket}>
                <TableCell className="font-medium">{finding.bucket}</TableCell>
                <TableCell>{finding.region}</TableCell>
                <TableCell className="text-muted-foreground">{finding.issue}</TableCell>
                <TableCell>{finding.storageClass}</TableCell>
                <TableCell className="min-w-44">{finding.footprint}</TableCell>
                <TableCell className="min-w-72">{finding.lifecycleAction}</TableCell>
                <TableCell className="text-right font-medium">
                  {formatCurrency(finding.estimatedSaving)}
                </TableCell>
                <TableCell><StatusBadge status={finding.status} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableCard>
    </div>
  )
}
