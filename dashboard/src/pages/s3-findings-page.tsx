import {
  ActivityIcon,
  ArchiveIcon,
  DollarSignIcon,
  LayersIcon,
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

import { getS3Findings } from "@/api/s3"
import {
  ChartCard,
  EmptyState,
  MetricCard,
  RawDetailsToggle,
  SectionHeader,
  StatusBadge,
} from "@/components/dashboard"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useApiData } from "@/hooks/use-api-data"
import { formatCurrency } from "@/lib/format"
import type { S3Finding } from "@/types/s3"

type DistributionPoint = {
  label: string
  count: number
}

type BucketSavingsPoint = {
  bucket: string
  estimatedSaving: number
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

function actionGroup(action: string | null | undefined) {
  const normalized = normalizeValue(action)

  if (!normalized) {
    return "Unknown"
  }
  if (
    normalized.includes("no_action") ||
    normalized.includes("exclude") ||
    normalized.includes("guardrail")
  ) {
    return "No action"
  }
  if (
    normalized.includes("transition") ||
    normalized.includes("archive") ||
    normalized.includes("glacier") ||
    normalized.includes("tier")
  ) {
    return "Transition / archive"
  }
  if (
    normalized.includes("expire") ||
    normalized.includes("delete") ||
    normalized.includes("clean") ||
    normalized.includes("remove")
  ) {
    return "Expire / delete"
  }

  return "Other action"
}

function findingStatusBadge(status: string | null | undefined) {
  const group = statusGroup(status)

  return <StatusBadge status={group} label={displayText(status)} />
}

function buildActionDistribution(findings: S3Finding[]) {
  const counts = new Map<string, number>([
    ["Transition / archive", 0],
    ["Expire / delete", 0],
    ["No action", 0],
    ["Other action", 0],
    ["Unknown", 0],
  ])

  findings.forEach((finding) => {
    const group = actionGroup(finding.lifecycleAction)
    counts.set(group, (counts.get(group) ?? 0) + 1)
  })

  return Array.from(counts, ([label, count]) => ({ label, count })).filter(
    (point) => point.count > 0
  )
}

function buildStatusDistribution(findings: S3Finding[]) {
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

  return Array.from(counts, ([label, count]) => ({ label, count })).filter(
    (point) => point.count > 0
  )
}

function buildBucketSavings(findings: S3Finding[]) {
  const savingsByBucket = new Map<string, BucketSavingsPoint>()

  findings.forEach((finding) => {
    const bucket = displayText(finding.bucket)
    const key = normalizeValue(finding.bucket) || bucket.toLowerCase()
    const existing = savingsByBucket.get(key)
    const estimatedSaving = safeNumber(finding.estimatedSaving)

    if (existing && existing.estimatedSaving >= estimatedSaving) {
      return
    }

    savingsByBucket.set(key, {
      bucket,
      estimatedSaving,
    })
  })

  return Array.from(savingsByBucket.values())
    .sort((left, right) => right.estimatedSaving - left.estimatedSaving)
    .slice(0, 8)
}

function buildTopRecommendations(findings: S3Finding[]) {
  const recommendationByBucket = new Map<string, S3Finding>()

  findings.forEach((finding) => {
    const key = normalizeValue(finding.bucket) || "unknown"
    const existing = recommendationByBucket.get(key)

    if (
      !existing ||
      safeNumber(finding.estimatedSaving) > safeNumber(existing.estimatedSaving)
    ) {
      recommendationByBucket.set(key, finding)
    }
  })

  return Array.from(recommendationByBucket.values())
    .sort((left, right) => safeNumber(right.estimatedSaving) - safeNumber(left.estimatedSaving))
    .slice(0, 5)
}

function truncateLabel(value: unknown) {
  const label = displayText(typeof value === "string" ? value : undefined)
  return label.length > 18 ? `${label.slice(0, 16)}...` : label
}

function CountChart({ data, color }: { data: DistributionPoint[]; color: string }) {
  return (
    <ResponsiveContainer
      width="100%"
      height="100%"
      minWidth={0}
      initialDimension={{ width: 350, height: 260 }}
    >
      <BarChart
        accessibilityLayer
        data={data}
        layout="vertical"
        margin={{ top: 8, right: 12, left: 18, bottom: 0 }}
      >
        <CartesianGrid horizontal={false} strokeDasharray="3 3" />
        <XAxis type="number" allowDecimals={false} axisLine={false} tickLine={false} />
        <YAxis
          type="category"
          dataKey="label"
          axisLine={false}
          tickLine={false}
          tickFormatter={truncateLabel}
          width={116}
        />
        <Tooltip formatter={(value) => [safeNumber(Number(value)), "Findings"]} />
        <Bar dataKey="count" fill={color} radius={[0, 5, 5, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

function RecommendationCard({ finding }: { finding: S3Finding }) {
  return (
    <Card className="shadow-xs">
      <CardContent className="space-y-4 p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h3 className="truncate font-medium">{displayText(finding.bucket)}</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              {displayText(finding.region)} | {displayText(finding.storageClass)}
            </p>
          </div>
          <div className="shrink-0 text-right">
            <p className="text-xs text-muted-foreground">Monthly saving</p>
            <p className="mt-1 text-lg font-semibold tabular-nums">
              {formatCurrency(safeNumber(finding.estimatedSaving))}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">{findingStatusBadge(finding.status)}</div>

        <div className="space-y-3 text-sm">
          <div>
            <p className="text-xs text-muted-foreground">Detected issue</p>
            <p className="mt-1">{displayText(finding.issue)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Lifecycle action</p>
            <p className="mt-1 leading-6">{displayText(finding.lifecycleAction)}</p>
          </div>
        </div>

        <div className="border-t pt-3 text-sm">
          <p className="text-xs text-muted-foreground">Estimated footprint</p>
          <p className="mt-1 font-medium">{displayText(finding.footprint)}</p>
        </div>
      </CardContent>
    </Card>
  )
}

function S3LoadingState() {
  return (
    <div className="space-y-6" aria-label="Loading S3 findings">
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
          Loading S3 storage optimization findings...
        </CardContent>
      </Card>
    </div>
  )
}

export function S3FindingsPage() {
  const { data, isLoading, error } = useApiData(getS3Findings)
  const findings = data ?? []

  const totalSavings = findings.reduce(
    (total, finding) => total + safeNumber(finding.estimatedSaving),
    0
  )
  const affectedBuckets = new Set(
    findings
      .map((finding) => finding.bucket?.trim())
      .filter((bucket): bucket is string => Boolean(bucket))
  ).size
  const blockedCount = findings.filter((finding) => statusGroup(finding.status) === "Blocked").length
  const lifecycleCount = findings.filter((finding) => {
    const group = actionGroup(finding.lifecycleAction)
    return group !== "No action" && group !== "Unknown"
  }).length
  const topSavings = buildBucketSavings(findings)
  const topRecommendations = buildTopRecommendations(findings)
  const actionDistribution = buildActionDistribution(findings)
  const statusDistribution = buildStatusDistribution(findings)

  return (
    <div className="space-y-6">
      <SectionHeader
        title="S3 Findings"
        description="S3 storage waste, lifecycle, and cost-optimization findings identified from the latest run."
        actions={<Button variant="outline">Export lifecycle plan</Button>}
      />

      {isLoading && <S3LoadingState />}

      {!isLoading && error && (
        <EmptyState
          title="S3 findings unavailable"
          description={error}
          icon={<TriangleAlertIcon />}
        />
      )}

      {!isLoading && !error && findings.length === 0 && (
        <EmptyState
          title="No S3 findings"
          description="No S3 storage optimization opportunities were reported for the latest run."
          icon={<ArchiveIcon />}
        />
      )}

      {!isLoading && !error && findings.length > 0 && (
        <>
          <section className="space-y-4">
            <SectionHeader
              title="S3 opportunity summary"
              description="Savings potential and lifecycle actions across the buckets surfaced by the pipeline."
            />
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
              <MetricCard
                title="Total S3 findings"
                value={findings.length}
                subtitle="Storage recommendations"
                icon={<ArchiveIcon />}
                variant="info"
              />
              <MetricCard
                title="Estimated monthly savings"
                value={formatCurrency(totalSavings)}
                subtitle="Across current S3 findings"
                icon={<DollarSignIcon />}
                variant="success"
              />
              <MetricCard
                title="Buckets affected"
                value={affectedBuckets}
                subtitle="Unique bucket identifiers"
                icon={<LayersIcon />}
                variant="info"
              />
              <MetricCard
                title="Blocked findings"
                value={blockedCount}
                subtitle="Excluded by safeguards"
                icon={<ShieldAlertIcon />}
                variant={blockedCount > 0 ? "danger" : "success"}
              />
              <MetricCard
                title="Lifecycle actions"
                value={lifecycleCount}
                subtitle="Transition, archive, expiry, or delete"
                icon={<ActivityIcon />}
                variant="warning"
              />
            </div>
          </section>

          <section className="space-y-4">
            <SectionHeader
              title="S3 visual analysis"
              description="Savings concentration and lifecycle outcomes calculated from current finding fields."
            />
            <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr_1fr]">
              <ChartCard
                title="Top savings by bucket"
                description="Up to eight buckets ranked by their highest estimated monthly saving finding."
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
                      dataKey="bucket"
                      axisLine={false}
                      tickLine={false}
                      tickFormatter={truncateLabel}
                      width={124}
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
                title="Lifecycle action distribution"
                description="Findings grouped by suggested storage lifecycle outcome."
              >
                <CountChart data={actionDistribution} color="var(--chart-3)" />
              </ChartCard>

              <ChartCard
                title="Status distribution"
                description="Findings grouped into action and review outcomes."
              >
                {statusDistribution.length === 0 ? (
                  <EmptyState
                    title="No status data"
                    description="Finding statuses are not available."
                    className="h-full"
                  />
                ) : (
                  <CountChart data={statusDistribution} color="var(--chart-4)" />
                )}
              </ChartCard>
            </div>
          </section>

          <section className="space-y-4">
            <SectionHeader
              title="Top S3 recommendations"
              description="Highest estimated monthly saving lifecycle opportunities, shown once per bucket."
            />
            <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
              {topRecommendations.map((finding, index) => (
                <RecommendationCard key={`${finding.bucket}-${index}`} finding={finding} />
              ))}
            </div>
          </section>

          <RawDetailsToggle
            title="Raw S3 details"
            description="Full bucket findings retained for inspection and verification."
          >
            <div className="overflow-x-auto">
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
                  {findings.map((finding, index) => (
                    <TableRow key={`${finding.bucket}-${index}`}>
                      <TableCell className="font-medium">{displayText(finding.bucket)}</TableCell>
                      <TableCell>{displayText(finding.region)}</TableCell>
                      <TableCell className="min-w-48 text-muted-foreground">
                        {displayText(finding.issue)}
                      </TableCell>
                      <TableCell>{displayText(finding.storageClass)}</TableCell>
                      <TableCell className="min-w-44">
                        {displayText(finding.footprint)}
                      </TableCell>
                      <TableCell className="min-w-72">
                        {displayText(finding.lifecycleAction)}
                      </TableCell>
                      <TableCell className="text-right font-medium">
                        {formatCurrency(safeNumber(finding.estimatedSaving))}
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
