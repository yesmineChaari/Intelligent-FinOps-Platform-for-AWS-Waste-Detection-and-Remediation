import {
  ActivityIcon,
  DollarSignIcon,
  ServerIcon,
  ShieldAlertIcon,
  TriangleAlertIcon,
} from "lucide-react"
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { getOverview } from "@/api/overview"
import { ChartCard } from "@/components/chart-card"
import { KpiCard } from "@/components/kpi-card"
import { PageHeader } from "@/components/page-header"
import { SeverityBadge } from "@/components/severity-badge"
import { StatusBadge } from "@/components/status-badge"
import { TableCard } from "@/components/table-card"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useApiData } from "@/hooks/use-api-data"
import { formatCurrency } from "@/lib/format"

export function OverviewPage() {
  const { data: overview, isLoading, error } = useApiData(getOverview)

  return (
    <div className="space-y-6">
      <PageHeader
        title="FinOps Overview"
        description="Estimated optimization value and pipeline safety posture for the latest mock run."
        actions={<Button variant="outline">Export summary</Button>}
      />

      {isLoading && (
        <Card>
          <CardContent className="p-8 text-center text-sm text-muted-foreground">
            Loading mock overview data...
          </CardContent>
        </Card>
      )}

      {error && (
        <Card>
          <CardContent className="p-8 text-center text-sm text-red-700">
            {error}
          </CardContent>
        </Card>
      )}

      {overview && (
        <>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <KpiCard
          label="Estimated monthly savings"
          value={formatCurrency(overview.totalEstimatedMonthlySavings)}
          detail="Across EC2 and S3 recommendations"
          icon={DollarSignIcon}
          tone="positive"
        />
        <KpiCard
          label="EC2 findings"
          value={String(overview.ec2FindingsCount)}
          detail="3 ready for optimization"
          icon={ServerIcon}
        />
        <KpiCard
          label="S3 findings"
          value={String(overview.s3FindingsCount)}
          detail="2 lifecycle actions approved"
          icon={ActivityIcon}
        />
        <KpiCard
          label="Blocked / risky"
          value={String(overview.blockedRiskyRecommendationsCount)}
          detail="Requires owner review"
          icon={ShieldAlertIcon}
          tone="warning"
        />
        <KpiCard
          label="Latest run"
          value={overview.latestRun.status}
          detail={`${overview.latestRun.runId} - ${overview.latestRun.duration}`}
          icon={TriangleAlertIcon}
          tone="positive"
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
        <ChartCard
          title="Savings trend"
          description="Estimated monthly savings surfaced by recent optimization runs."
        >
          <ResponsiveContainer
            width="100%"
            height="100%"
            minWidth={0}
            initialDimension={{ width: 640, height: 260 }}
          >
            <AreaChart data={overview.savingsTrend} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="savings-fill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#059669" stopOpacity={0.28} />
                  <stop offset="95%" stopColor="#059669" stopOpacity={0.03} />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} strokeDasharray="3 3" />
              <XAxis dataKey="month" axisLine={false} tickLine={false} />
              <YAxis
                axisLine={false}
                tickLine={false}
                tickFormatter={(value: number) => `$${value}`}
                width={52}
              />
              <Tooltip
                formatter={(value) => [formatCurrency(Number(value)), "Savings"]}
                cursor={{ stroke: "#cbd5e1", strokeDasharray: "4 4" }}
              />
              <Area
                dataKey="savings"
                type="monotone"
                fill="url(#savings-fill)"
                stroke="#059669"
                strokeWidth={2}
              />
            </AreaChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard
          title="Findings by type"
          description="Current findings grouped by optimization action."
        >
          <ResponsiveContainer
            width="100%"
            height="100%"
            minWidth={0}
            initialDimension={{ width: 420, height: 260 }}
          >
            <BarChart data={overview.findingsByType} layout="vertical" margin={{ left: 16, right: 16 }}>
              <CartesianGrid horizontal={false} strokeDasharray="3 3" />
              <XAxis type="number" allowDecimals={false} axisLine={false} tickLine={false} />
              <YAxis
                type="category"
                dataKey="type"
                axisLine={false}
                tickLine={false}
                width={92}
              />
              <Tooltip cursor={{ fill: "#f1f5f9" }} />
              <Bar dataKey="count" fill="#0f766e" radius={[0, 5, 5, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>

      <TableCard
        title="Recent alerts"
        description="Safety and pipeline notifications surfaced during recent evaluations."
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Severity</TableHead>
              <TableHead>Alert type</TableHead>
              <TableHead>Message</TableHead>
              <TableHead>Resource</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Created</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {overview.recentAlerts.slice(0, 4).map((alert) => (
              <TableRow key={`${alert.type}-${alert.resource}`}>
                <TableCell><SeverityBadge level={alert.severity} /></TableCell>
                <TableCell className="font-medium">{alert.type}</TableCell>
                <TableCell className="max-w-md text-muted-foreground">{alert.message}</TableCell>
                <TableCell>{alert.resource}</TableCell>
                <TableCell><StatusBadge status={alert.status} /></TableCell>
                <TableCell className="text-muted-foreground">{alert.createdAt}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableCard>
        </>
      )}
    </div>
  )
}
