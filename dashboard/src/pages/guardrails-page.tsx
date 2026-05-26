import {
  ActivityIcon,
  ArrowRightIcon,
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

import { getGuardrailResults } from "@/api/guardrails"
import {
  ChartCard,
  EmptyState,
  MetricCard,
  RawDetailsToggle,
  RiskBadge,
  SectionHeader,
  StatusBadge,
} from "@/components/dashboard"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useApiData } from "@/hooks/use-api-data"
import { cn } from "@/lib/utils"
import type { GuardrailDecision } from "@/types/guardrails"

type DistributionPoint = {
  label: string
  count: number
}

type OutcomeGroup = "Blocked" | "Review" | "Changed" | "Kept" | "Unknown"

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

function outcomeGroup(decision: GuardrailDecision): OutcomeGroup {
  const outcome = normalizeValue(decision.outcome)
  const finalDecision = normalizeValue(decision.finalDecision)

  if (outcome.includes("block") || finalDecision.includes("block")) {
    return "Blocked"
  }
  if (
    outcome.includes("review") ||
    outcome.includes("manual") ||
    finalDecision.includes("review") ||
    finalDecision.includes("manual")
  ) {
    return "Review"
  }
  if (outcome.includes("change") || outcome.includes("modify") || outcome.includes("alter")) {
    return "Changed"
  }
  if (
    outcome.includes("keep") ||
    outcome.includes("allow") ||
    outcome.includes("approve")
  ) {
    return "Kept"
  }

  return "Unknown"
}

function buildOutcomeDistribution(decisions: GuardrailDecision[]) {
  const counts = new Map<string, number>([
    ["Blocked", 0],
    ["Review", 0],
    ["Changed", 0],
    ["Kept", 0],
    ["Unknown", 0],
  ])

  decisions.forEach((decision) => {
    const group = outcomeGroup(decision)
    counts.set(group, (counts.get(group) ?? 0) + 1)
  })

  return Array.from(counts, ([label, count]) => ({ label, count })).filter(
    (point) => point.count > 0
  )
}

function buildRiskDistribution(decisions: GuardrailDecision[]) {
  const counts = new Map<string, number>([
    ["Low", 0],
    ["Medium", 0],
    ["High", 0],
    ["Critical", 0],
    ["Unknown", 0],
  ])

  decisions.forEach((decision) => {
    const group = riskGroup(decision.risk)
    counts.set(group, (counts.get(group) ?? 0) + 1)
  })

  return Array.from(counts, ([label, count]) => ({ label, count })).filter(
    (point) => point.count > 0
  )
}

function decisionPriority(decision: GuardrailDecision) {
  const outcome = outcomeGroup(decision)
  const risk = riskGroup(decision.risk)

  if (outcome === "Blocked") {
    return 0
  }
  if (outcome === "Review") {
    return 1
  }
  if (risk === "High" || risk === "Critical") {
    return 2
  }

  return 3
}

function safeCount(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0
}

function CountChart({ data, color }: { data: DistributionPoint[]; color: string }) {
  return (
    <ResponsiveContainer
      width="100%"
      height="100%"
      minWidth={0}
      initialDimension={{ width: 350, height: 260 }}
    >
      <BarChart accessibilityLayer data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
        <CartesianGrid vertical={false} strokeDasharray="3 3" />
        <XAxis dataKey="label" axisLine={false} tickLine={false} tickMargin={8} />
        <YAxis type="number" allowDecimals={false} axisLine={false} tickLine={false} />
        <Tooltip formatter={(value) => [safeCount(Number(value)), "Decisions"]} />
        <Bar dataKey="count" fill={color} radius={[5, 5, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

function DecisionFlowCard({ decision }: { decision: GuardrailDecision }) {
  const outcome = outcomeGroup(decision)
  const risk = riskGroup(decision.risk)
  const needsAttention =
    outcome === "Blocked" || outcome === "Review" || risk === "High" || risk === "Critical"

  return (
    <Card
      className={cn(
        "shadow-xs",
        needsAttention && "border-l-4 border-l-amber-500",
        outcome === "Blocked" && "border-l-red-500"
      )}
    >
      <CardContent className="space-y-5 p-5">
        <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">Resource</p>
            <h3 className="mt-1 font-medium">{displayText(decision.resource)}</h3>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            <RiskBadge risk={decision.risk} />
            <StatusBadge status={outcome} label={displayText(decision.outcome)} />
          </div>
        </div>

        <div className="grid items-stretch gap-2 lg:grid-cols-[1fr_auto_1fr_auto_minmax(9rem,0.7fr)]">
          <div className="rounded-lg border bg-muted/20 p-3">
            <p className="text-xs text-muted-foreground">Phase 1 recommendation</p>
            <p className="mt-2 leading-6">{displayText(decision.originalRecommendation)}</p>
          </div>
          <ArrowRightIcon className="hidden size-4 self-center text-muted-foreground lg:block" aria-hidden="true" />
          <div className="rounded-lg border bg-muted/20 p-3">
            <p className="text-xs text-muted-foreground">Guardrail decision / safe action</p>
            <p className="mt-2 leading-6">{displayText(decision.finalDecision)}</p>
          </div>
          <ArrowRightIcon className="hidden size-4 self-center text-muted-foreground lg:block" aria-hidden="true" />
          <div className="rounded-lg border bg-muted/20 p-3">
            <p className="text-xs text-muted-foreground">Outcome</p>
            <div className="mt-2">
              <StatusBadge status={outcome} label={displayText(decision.outcome)} />
            </div>
          </div>
        </div>

        <div className="grid gap-4 border-t pt-4 md:grid-cols-[minmax(10rem,0.7fr)_1fr]">
          <div>
            <p className="text-xs text-muted-foreground">Blast radius</p>
            <p className="mt-1 leading-6">{displayText(decision.blastRadius)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Decision rationale</p>
            <p className="mt-1 leading-6 text-muted-foreground">{displayText(decision.reason)}</p>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function GuardrailsLoadingState() {
  return (
    <div className="space-y-6" aria-label="Loading guardrail decisions">
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
        <CardContent className="space-y-3 p-5">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-32 w-full" />
        </CardContent>
      </Card>
    </div>
  )
}

export function GuardrailsPage() {
  const { data, isLoading, error } = useApiData(getGuardrailResults)
  const decisions = data ?? []

  const outcomeDistribution = buildOutcomeDistribution(decisions)
  const riskDistribution = buildRiskDistribution(decisions)
  const prioritizedDecisions = [...decisions].sort(
    (left, right) => decisionPriority(left) - decisionPriority(right)
  )
  const blockedCount = decisions.filter((decision) => outcomeGroup(decision) === "Blocked").length
  const changedCount = decisions.filter((decision) => outcomeGroup(decision) === "Changed").length
  const keptCount = decisions.filter((decision) => outcomeGroup(decision) === "Kept").length
  const elevatedRiskCount = decisions.filter((decision) => {
    const risk = riskGroup(decision.risk)
    return risk === "High" || risk === "Critical"
  }).length

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Guardrails"
        description="Phase 2 validates, changes, or blocks Phase 1 recommendations before a final safe action is carried forward."
      />

      {isLoading ? (
        <GuardrailsLoadingState />
      ) : error ? (
        <EmptyState
          title="Guardrail decisions could not be loaded"
          description={error}
          icon={<TriangleAlertIcon />}
        />
      ) : decisions.length === 0 ? (
        <EmptyState
          title="No guardrail decisions available"
          description="No Phase 2 validation results were returned for the latest run."
          icon={<ShieldAlertIcon />}
        />
      ) : (
        <>
          <section className="space-y-4">
            <SectionHeader
              title="Decision summary"
              description="Policy outcomes and risk exposure calculated from the current Phase 2 results."
            />
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
              <MetricCard
                title="Total decisions"
                value={decisions.length}
                subtitle="Resources evaluated"
                icon={<ActivityIcon />}
                variant="info"
              />
              <MetricCard
                title="Blocked decisions"
                value={blockedCount}
                subtitle="Unsafe actions prevented"
                icon={<ShieldAlertIcon />}
                variant={blockedCount > 0 ? "danger" : "default"}
              />
              <MetricCard
                title="Changed decisions"
                value={changedCount}
                subtitle="Safer action substituted"
                icon={<TriangleAlertIcon />}
                variant={changedCount > 0 ? "warning" : "default"}
              />
              <MetricCard
                title="Approved or kept"
                value={keptCount}
                subtitle="Original recommendation retained"
                icon={<ActivityIcon />}
                variant="success"
              />
              <MetricCard
                title="High or critical risk"
                value={elevatedRiskCount}
                subtitle="Priority review exposure"
                icon={<ShieldAlertIcon />}
                variant={elevatedRiskCount > 0 ? "danger" : "default"}
              />
            </div>
          </section>

          <section className="space-y-4">
            <SectionHeader
              title="Decision outcomes"
              description="How Phase 2 resolves recommendations and where elevated operational risk remains."
            />
            <div className="grid gap-4 xl:grid-cols-2">
              <ChartCard
                title="Outcome distribution"
                description="Guardrail decisions grouped by final outcome."
              >
                <CountChart data={outcomeDistribution} color="var(--chart-2)" />
              </ChartCard>
              <ChartCard
                title="Risk distribution"
                description="Decisions grouped by existing risk classification."
              >
                {riskDistribution.length > 0 ? (
                  <CountChart data={riskDistribution} color="var(--chart-3)" />
                ) : (
                  <EmptyState
                    title="No risk classifications"
                    description="Risk values were not provided for these decisions."
                    className="h-full"
                  />
                )}
              </ChartCard>
            </div>
          </section>

          <section className="space-y-4">
            <SectionHeader
              title="Decision flow"
              description="Blocked decisions appear first, followed by manual-review signals and high-risk outcomes."
            />
            <div className="space-y-4">
              {prioritizedDecisions.map((decision, index) => (
                <DecisionFlowCard key={`${decision.resource}-${index}`} decision={decision} />
              ))}
            </div>
          </section>

          <RawDetailsToggle
            title="Raw guardrail details"
            description="Complete Phase 2 result fields retained for inspection and audit."
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
                {decisions.map((decision, index) => (
                  <TableRow key={`${decision.resource}-${index}`}>
                    <TableCell className="min-w-56 font-medium">
                      {displayText(decision.resource)}
                    </TableCell>
                    <TableCell className="min-w-60">
                      {displayText(decision.originalRecommendation)}
                    </TableCell>
                    <TableCell className="min-w-60">
                      {displayText(decision.finalDecision)}
                    </TableCell>
                    <TableCell>
                      <StatusBadge
                        status={outcomeGroup(decision)}
                        label={displayText(decision.outcome)}
                      />
                    </TableCell>
                    <TableCell>
                      <RiskBadge risk={decision.risk} />
                    </TableCell>
                    <TableCell className="min-w-48">
                      {displayText(decision.blastRadius)}
                    </TableCell>
                    <TableCell className="min-w-72 text-muted-foreground">
                      {displayText(decision.reason)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </RawDetailsToggle>
        </>
      )}
    </div>
  )
}
