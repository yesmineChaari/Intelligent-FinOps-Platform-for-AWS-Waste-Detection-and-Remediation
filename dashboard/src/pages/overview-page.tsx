import {
  ActivityIcon,
  BellIcon,
  ChartColumnIcon,
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
import {
  ChartCard,
  EmptyState,
  MetricCard,
  RawDetailsToggle,
  SectionHeader,
  StatusBadge,
  type MetricCardVariant,
} from "@/components/dashboard"
import { PageHeader } from "@/components/page-header"
import { SeverityBadge } from "@/components/severity-badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useApiData } from "@/hooks/use-api-data"
import { formatCurrency } from "@/lib/format"
import type { AlertSeverity } from "@/types/alerts"
import type { Overview } from "@/types/overview"

function safeNumber(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0
}

function displayText(value: string | null | undefined, fallback = "Unavailable") {
  return value?.trim() || fallback
}

function countLabel(count: number, singular: string) {
  return `${count} ${count === 1 ? singular : `${singular}s`}`
}

function latestRunVariant(status: string): MetricCardVariant {
  const normalized = status.toLowerCase()

  if (normalized.includes("complete") || normalized.includes("success")) {
    return "success"
  }
  if (normalized.includes("fail") || normalized.includes("error")) {
    return "danger"
  }
  if (normalized.includes("run") || normalized.includes("progress")) {
    return "info"
  }

  return "default"
}

function buildRunNarrative(overview: Overview) {
  const status = displayText(overview.latestRun?.status, "unknown status").toLowerCase()
  const ec2Findings = safeNumber(overview.ec2FindingsCount)
  const s3Findings = safeNumber(overview.s3FindingsCount)
  const blocked = safeNumber(overview.blockedRiskyRecommendationsCount)
  const savings = formatCurrency(safeNumber(overview.totalEstimatedMonthlySavings))

  return `Latest run ${status}. It found ${countLabel(ec2Findings, "EC2 finding")} and ${countLabel(s3Findings, "S3 finding")}, with estimated monthly savings of ${savings}. ${countLabel(blocked, "recommendation")} ${blocked === 1 ? "was" : "were"} blocked or routed for review by guardrails.`
}

const alertSeverities: Record<string, AlertSeverity> = {
  critical: "Critical",
  high: "High",
  info: "Info",
  warning: "Warning",
}

function AlertSeverityBadge({ severity }: { severity?: string | null }) {
  const normalized = severity?.trim().toLowerCase()
  const knownSeverity = normalized ? alertSeverities[normalized] : undefined

  return knownSeverity ? <SeverityBadge level={knownSeverity} /> : <StatusBadge label="Unknown" />
}

function ChartEmpty({ message }: { message: string }) {
  return (
    <div className="flex h-full items-center justify-center rounded-lg border border-dashed px-4 text-center text-sm text-muted-foreground">
      {message}
    </div>
  )
}

function OverviewLoadingState() {
  return (
    <div className="space-y-6" aria-label="Loading overview summary">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        {Array.from({ length: 5 }, (_, index) => (
          <Card key={index} className="shadow-xs">
            <CardContent className="space-y-3 p-5">
              <Skeleton className="h-4 w-28" />
              <Skeleton className="h-8 w-24" />
              <Skeleton className="h-3 w-36" />
            </CardContent>
          </Card>
        ))}
      </div>
      <Card className="shadow-xs">
        <CardContent className="p-8 text-center text-sm text-muted-foreground">
          Loading the latest optimization run summary...
        </CardContent>
      </Card>
    </div>
  )
}

export function OverviewPage() {
  const { data: overview, isLoading, error } = useApiData(getOverview)

  const runId = displayText(overview?.latestRun?.runId)
  const runStatus = displayText(overview?.latestRun?.status)
  const noLatestRun = runId.toLowerCase() === "unavailable"
  const savingsTrend = overview?.savingsTrend ?? []
  const findingsByType = overview?.findingsByType ?? []
  const recentAlerts = overview?.recentAlerts ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        title="FinOps Overview"
        description="Executive summary of cost optimization opportunities and guardrail outcomes for the latest run."
        actions={<Button variant="outline">Export summary</Button>}
      />

      {isLoading && <OverviewLoadingState />}

      {!isLoading && error && (
        <EmptyState
          title="Overview unavailable"
          description={error}
          icon={<TriangleAlertIcon />}
        />
      )}

      {!isLoading && !error && (!overview || noLatestRun) && (
        <EmptyState
          title="No optimization run available"
          description="There is no completed pipeline output to summarize yet."
          icon={<ActivityIcon />}
        />
      )}

      {!isLoading && !error && overview && !noLatestRun && (
        <>
          <section className="space-y-4">
            <SectionHeader
              title="Latest run at a glance"
              description="Potential monthly savings and attention items from the most recent pipeline output."
            />
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
              <MetricCard
                title="Estimated monthly savings"
                value={formatCurrency(safeNumber(overview.totalEstimatedMonthlySavings))}
                subtitle="Across EC2 and S3 findings"
                icon={<DollarSignIcon />}
                variant="success"
              />
              <MetricCard
                title="EC2 findings"
                value={safeNumber(overview.ec2FindingsCount)}
                subtitle="Compute optimization findings"
                icon={<ServerIcon />}
                variant="info"
              />
              <MetricCard
                title="S3 findings"
                value={safeNumber(overview.s3FindingsCount)}
                subtitle="Storage lifecycle findings"
                icon={<ChartColumnIcon />}
                variant="info"
              />
              <MetricCard
                title="Blocked risky recommendations"
                value={safeNumber(overview.blockedRiskyRecommendationsCount)}
                subtitle="Guardrail attention required"
                icon={<ShieldAlertIcon />}
                variant={safeNumber(overview.blockedRiskyRecommendationsCount) > 0 ? "warning" : "success"}
              />
              <MetricCard
                title="Latest run status"
                value={<StatusBadge status={runStatus} className="h-7 px-3 text-sm" />}
                subtitle={`${runId} | ${displayText(overview.latestRun?.duration)}`}
                icon={<ActivityIcon />}
                variant={latestRunVariant(runStatus)}
              />
            </div>
          </section>

          <section className="space-y-4">
            <SectionHeader
              title="Latest run summary"
              description="Plain-language interpretation of the available optimization totals."
            />
            <Card className="shadow-xs">
              <CardContent className="flex gap-4 p-5 md:p-6">
                <div className="hidden shrink-0 rounded-lg bg-emerald-50 p-3 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300 sm:block">
                  <ActivityIcon className="size-5" />
                </div>
                <p className="text-sm leading-7 text-foreground md:text-base">
                  {buildRunNarrative(overview)}
                </p>
              </CardContent>
            </Card>
          </section>

          <section className="space-y-4">
            <SectionHeader
              title="Optimization signals"
              description="Visual trends and the current mix of findings reported by the latest run."
            />
            <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
              <ChartCard
                title="Savings trend"
                description="Estimated monthly savings surfaced by recent optimization runs."
              >
                {savingsTrend.length === 0 ? (
                  <ChartEmpty message="No savings trend data is available." />
                ) : (
                  <ResponsiveContainer
                    width="100%"
                    height="100%"
                    minWidth={0}
                    initialDimension={{ width: 640, height: 260 }}
                  >
                    <AreaChart
                      accessibilityLayer
                      data={savingsTrend}
                      margin={{ top: 8, right: 12, left: 0, bottom: 0 }}
                    >
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
                        tickFormatter={(value: number) => formatCurrency(safeNumber(value))}
                        width={70}
                      />
                      <Tooltip
                        formatter={(value) => [formatCurrency(safeNumber(Number(value))), "Savings"]}
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
                )}
              </ChartCard>

              <ChartCard
                title="Findings by type"
                description="Latest-run findings grouped by detected optimization type."
              >
                {findingsByType.length === 0 ? (
                  <ChartEmpty message="No finding type data is available." />
                ) : (
                  <ResponsiveContainer
                    width="100%"
                    height="100%"
                    minWidth={0}
                    initialDimension={{ width: 420, height: 260 }}
                  >
                    <BarChart
                      accessibilityLayer
                      data={findingsByType}
                      layout="vertical"
                      margin={{ left: 16, right: 16 }}
                    >
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
                )}
              </ChartCard>
            </div>
          </section>

          <section className="space-y-4">
            <SectionHeader
              title="Recent alerts"
              description="Safety and pipeline notifications that may require operator attention."
            />
            {recentAlerts.length === 0 ? (
              <EmptyState
                title="No recent alerts"
                description="No safety or pipeline alerts were reported for the current dashboard view."
                icon={<BellIcon />}
              />
            ) : (
              <>
                <div className="grid gap-4 lg:grid-cols-2">
                  {recentAlerts.map((alert, index) => (
                    <Card key={`${alert.type}-${alert.resource}-${index}`} className="shadow-xs">
                      <CardContent className="space-y-4 p-5">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <h3 className="font-medium">{displayText(alert.type)}</h3>
                            <p className="mt-2 text-sm leading-6 text-muted-foreground">
                              {displayText(alert.message)}
                            </p>
                          </div>
                          <AlertSeverityBadge severity={alert.severity} />
                        </div>
                        <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-3 text-xs">
                          <div className="flex flex-wrap items-center gap-2 text-muted-foreground">
                            <span>{displayText(alert.resource)}</span>
                            <span aria-hidden="true">|</span>
                            <span>{displayText(alert.createdAt)}</span>
                          </div>
                          <StatusBadge status={alert.status} />
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </div>

                <RawDetailsToggle
                  title="Raw alert details"
                  description="Full alert fields retained for drill-down and verification."
                >
                  <div className="overflow-x-auto">
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
                        {recentAlerts.map((alert, index) => (
                          <TableRow key={`${alert.type}-${alert.resource}-${index}`}>
                            <TableCell>
                              <AlertSeverityBadge severity={alert.severity} />
                            </TableCell>
                            <TableCell className="font-medium">{displayText(alert.type)}</TableCell>
                            <TableCell className="min-w-80 text-muted-foreground">
                              {displayText(alert.message)}
                            </TableCell>
                            <TableCell>{displayText(alert.resource)}</TableCell>
                            <TableCell>
                              <StatusBadge status={alert.status} />
                            </TableCell>
                            <TableCell className="text-muted-foreground">
                              {displayText(alert.createdAt)}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </RawDetailsToggle>
              </>
            )}
          </section>
        </>
      )}
    </div>
  )
}
