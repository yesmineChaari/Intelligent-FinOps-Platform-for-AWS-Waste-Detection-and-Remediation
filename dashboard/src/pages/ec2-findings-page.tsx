import {
  ActivityIcon,
  DollarSignIcon,
  ServerIcon,
  ShieldAlertIcon,
  TriangleAlertIcon,
} from "lucide-react"
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { getEc2Findings } from "@/api/ec2"
import {
  ChartCard,
  EmptyState,
  MetricCard,
  RawDetailsToggle,
  RiskBadge,
  SectionHeader,
  StatusBadge,
} from "@/components/dashboard"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useApiData } from "@/hooks/use-api-data"
import { formatCurrency } from "@/lib/format"
import type { Ec2Finding } from "@/types/ec2"

type DistributionPoint = {
  label: string
  count: number
}

function safeNumber(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0
}

function displayText(value: string | null | undefined, fallback = "Unknown") {
  return value?.trim() || fallback
}

function normalizeValue(value: string | null | undefined) {
  return value?.trim().toLowerCase().replace(/[\s-]+/g, "_") ?? ""
}

function riskGroup(risk: string | null | undefined) {
  const normalized = normalizeValue(risk)

  if (
    normalized === "low" ||
    normalized === "medium" ||
    normalized === "high" ||
    normalized === "critical"
  ) {
    return `${normalized.charAt(0).toUpperCase()}${normalized.slice(1)}`
  }

  return "Unknown"
}

function statusGroup(status: string | null | undefined) {
  const normalized = normalizeValue(status)

  if (normalized.includes("block") || normalized.includes("skip") || normalized.includes("fail")) {
    return "Blocked"
  }
  if (
    normalized.includes("review") ||
    normalized.includes("pending") ||
    normalized.includes("manual")
  ) {
    return "Review"
  }
  if (
    normalized.includes("recommend") ||
    normalized.includes("approve") ||
    normalized.includes("complete")
  ) {
    return "Recommended"
  }

  return "Unknown"
}

function findingStatusBadge(status: string | null | undefined) {
  const group = statusGroup(status)

  return <StatusBadge status={group} label={displayText(status)} />
}

function buildRiskDistribution(findings: Ec2Finding[]) {
  const counts = new Map<string, number>([
    ["Low", 0],
    ["Medium", 0],
    ["High", 0],
    ["Critical", 0],
    ["Unknown", 0],
  ])

  findings.forEach((finding) => {
    const group = riskGroup(finding.risk)
    counts.set(group, (counts.get(group) ?? 0) + 1)
  })

  return Array.from(counts, ([label, count]) => ({ label, count }))
}

function buildStatusDistribution(findings: Ec2Finding[]) {
  const counts = new Map<string, number>([
    ["Recommended", 0],
    ["Blocked", 0],
    ["Review", 0],
    ["Unknown", 0],
  ])

  findings.forEach((finding) => {
    const group = statusGroup(finding.status)
    counts.set(group, (counts.get(group) ?? 0) + 1)
  })

  return Array.from(counts, ([label, count]) => ({ label, count }))
}

function truncateLabel(value: unknown) {
  const label = displayText(typeof value === "string" ? value : undefined)
  return label.length > 16 ? `${label.slice(0, 14)}...` : label
}

function CountChart({ data, color }: { data: DistributionPoint[]; color: string }) {
  return (
    <ResponsiveContainer
      width="100%"
      height="100%"
      minWidth={0}
      initialDimension={{ width: 340, height: 260 }}
    >
      <BarChart accessibilityLayer data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
        <CartesianGrid vertical={false} strokeDasharray="3 3" />
        <XAxis dataKey="label" axisLine={false} tickLine={false} tickMargin={8} />
        <YAxis type="number" allowDecimals={false} axisLine={false} tickLine={false} />
        <Tooltip formatter={(value) => [safeNumber(Number(value)), "Findings"]} />
        <Bar dataKey="count" fill={color} radius={[5, 5, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

function RecommendationCard({ finding }: { finding: Ec2Finding }) {
  return (
    <Card className="shadow-xs">
      <CardContent className="space-y-4 p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h3 className="truncate font-medium">{displayText(finding.instance)}</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              {displayText(finding.instanceType)} | {displayText(finding.region)}
            </p>
          </div>
          <div className="shrink-0 text-right">
            <p className="text-xs text-muted-foreground">Monthly saving</p>
            <p className="mt-1 text-lg font-semibold tabular-nums">
              {formatCurrency(safeNumber(finding.estimatedSaving))}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <RiskBadge risk={finding.risk} />
          {findingStatusBadge(finding.status)}
        </div>

        <div className="space-y-3 text-sm">
          <div>
            <p className="text-xs text-muted-foreground">Detected issue</p>
            <p className="mt-1">{displayText(finding.issue)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Recommendation</p>
            <p className="mt-1 leading-6">{displayText(finding.recommendation)}</p>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3 border-t pt-3 text-sm">
          <div>
            <p className="text-xs text-muted-foreground">CPU avg</p>
            <p className="mt-1 font-medium tabular-nums">{displayText(finding.cpuAverage)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">CPU p95</p>
            <p className="mt-1 font-medium tabular-nums">{displayText(finding.cpuP95)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Memory avg</p>
            <p className="mt-1 font-medium tabular-nums">{displayText(finding.memoryAverage)}</p>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function Ec2LoadingState() {
  return (
    <div className="space-y-6" aria-label="Loading EC2 findings">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        {Array.from({ length: 5 }, (_, index) => (
          <Card key={index} className="shadow-xs">
            <CardContent className="space-y-3 p-5">
              <Skeleton className="h-4 w-28" />
              <Skeleton className="h-8 w-20" />
              <Skeleton className="h-3 w-32" />
            </CardContent>
          </Card>
        ))}
      </div>
      <Card className="shadow-xs">
        <CardContent className="p-8 text-center text-sm text-muted-foreground">
          Loading EC2 optimization findings...
        </CardContent>
      </Card>
    </div>
  )
}

export function Ec2FindingsPage() {
  const { data, isLoading, error } = useApiData(getEc2Findings)
  const findings = data ?? []

  const totalSavings = findings.reduce(
    (total, finding) => total + safeNumber(finding.estimatedSaving),
    0
  )
  const blockedCount = findings.filter((finding) => statusGroup(finding.status) === "Blocked").length
  const reviewCount = findings.filter((finding) => statusGroup(finding.status) === "Review").length
  const highRiskCount = findings.filter((finding) => {
    const group = riskGroup(finding.risk)
    return group === "High" || group === "Critical"
  }).length
  const topSavings = [...findings]
    .sort((left, right) => safeNumber(right.estimatedSaving) - safeNumber(left.estimatedSaving))
    .slice(0, 8)
  const topRecommendations = topSavings.slice(0, 5)
  const riskDistribution = buildRiskDistribution(findings)
  const statusDistribution = buildStatusDistribution(findings)

  return (
    <div className="space-y-6">
      <SectionHeader
        title="EC2 Findings"
        description="EC2 waste and optimization recommendations identified from the latest pipeline run."
        actions={<Button variant="outline">Filter findings</Button>}
      />

      {isLoading && <Ec2LoadingState />}

      {!isLoading && error && (
        <EmptyState
          title="EC2 findings unavailable"
          description={error}
          icon={<TriangleAlertIcon />}
        />
      )}

      {!isLoading && !error && findings.length === 0 && (
        <EmptyState
          title="No EC2 findings"
          description="No EC2 optimization opportunities were reported for the latest run."
          icon={<ServerIcon />}
        />
      )}

      {!isLoading && !error && findings.length > 0 && (
        <>
          <section className="space-y-4">
            <SectionHeader
              title="EC2 opportunity summary"
              description="Savings potential, guardrail attention, and risk indicators across all findings."
            />
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
              <MetricCard
                title="Total EC2 findings"
                value={findings.length}
                subtitle="Instances requiring assessment"
                icon={<ServerIcon />}
                variant="info"
              />
              <MetricCard
                title="Estimated monthly savings"
                value={formatCurrency(totalSavings)}
                subtitle="Across current EC2 findings"
                icon={<DollarSignIcon />}
                variant="success"
              />
              <MetricCard
                title="Blocked findings"
                value={blockedCount}
                subtitle="Stopped by safeguards"
                icon={<ShieldAlertIcon />}
                variant={blockedCount > 0 ? "danger" : "success"}
              />
              <MetricCard
                title="Manual review"
                value={reviewCount}
                subtitle="Pending or ready for review"
                icon={<ActivityIcon />}
                variant={reviewCount > 0 ? "warning" : "default"}
              />
              <MetricCard
                title="High or critical risk"
                value={highRiskCount}
                subtitle="Findings needing caution"
                icon={<TriangleAlertIcon />}
                variant={highRiskCount > 0 ? "danger" : "success"}
              />
            </div>
          </section>

          <section className="space-y-4">
            <SectionHeader
              title="EC2 visual analysis"
              description="Savings concentration and finding classifications from available EC2 output fields."
            />
            <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr_1fr]">
              <ChartCard
                title="Top savings by instance"
                description="Up to eight EC2 findings ranked by estimated monthly saving."
              >
                <ResponsiveContainer
                  width="100%"
                  height="100%"
                  minWidth={0}
                  initialDimension={{ width: 520, height: 260 }}
                >
                  <BarChart
                    accessibilityLayer
                    data={topSavings}
                    layout="vertical"
                    margin={{ top: 8, right: 18, left: 10, bottom: 0 }}
                  >
                    <CartesianGrid horizontal={false} strokeDasharray="3 3" />
                    <XAxis
                      type="number"
                      axisLine={false}
                      tickLine={false}
                      tickFormatter={(value: number) => formatCurrency(safeNumber(value))}
                    />
                    <YAxis
                      type="category"
                      dataKey="instance"
                      axisLine={false}
                      tickLine={false}
                      tickFormatter={truncateLabel}
                      width={116}
                    />
                    <Tooltip
                      formatter={(value) => [
                        formatCurrency(safeNumber(Number(value))),
                        "Estimated savings",
                      ]}
                    />
                    <Bar dataKey="estimatedSaving" fill="var(--chart-2)" radius={[0, 5, 5, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </ChartCard>

              <ChartCard
                title="Risk distribution"
                description="Findings grouped by current risk classification."
              >
                <CountChart data={riskDistribution} color="var(--chart-3)" />
              </ChartCard>

              <ChartCard
                title="Status distribution"
                description="Findings grouped into action and review outcomes."
              >
                <CountChart data={statusDistribution} color="var(--chart-4)" />
              </ChartCard>
            </div>
          </section>

          <section className="space-y-4">
            <SectionHeader
              title="Top EC2 recommendations"
              description="Highest estimated monthly saving opportunities surfaced for operator review."
            />
            <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
              {topRecommendations.map((finding, index) => (
                <RecommendationCard
                  key={`${finding.instance}-${index}`}
                  finding={finding}
                />
              ))}
            </div>
          </section>

          <RawDetailsToggle
            title="Raw EC2 details"
            description="Full fields retained for inspection and verification."
          >
            <div className="overflow-x-auto">
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
                  {findings.map((finding, index) => (
                    <TableRow key={`${finding.instance}-${index}`}>
                      <TableCell className="min-w-56 font-medium">
                        {displayText(finding.instance)}
                      </TableCell>
                      <TableCell>{displayText(finding.region)}</TableCell>
                      <TableCell>{displayText(finding.instanceType)}</TableCell>
                      <TableCell className="min-w-48 text-muted-foreground">
                        {displayText(finding.issue)}
                      </TableCell>
                      <TableCell>{displayText(finding.cpuAverage)}</TableCell>
                      <TableCell>{displayText(finding.cpuP95)}</TableCell>
                      <TableCell>{displayText(finding.memoryAverage)}</TableCell>
                      <TableCell className="min-w-48">
                        {displayText(finding.recommendation)}
                      </TableCell>
                      <TableCell className="text-right font-medium">
                        {formatCurrency(safeNumber(finding.estimatedSaving))}
                      </TableCell>
                      <TableCell>
                        <RiskBadge risk={finding.risk} />
                      </TableCell>
                      <TableCell>{findingStatusBadge(finding.status)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </RawDetailsToggle>
        </>
      )}
    </div>
  )
}
