import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const limit = Math.min(parseInt(searchParams.get('limit') ?? '20', 10), 100);

  try {
    const [failedRuns, blockedGuardrails, ec2ParseErrors, s3ParseErrors] = await Promise.all([
      sql`
        SELECT id, status, error_message, started_at
        FROM optimization_runs
        WHERE status IN ('failed', 'phase3_failed')
        ORDER BY started_at DESC
        LIMIT ${limit}
      `,
      sql`
        WITH latest_run AS (
          SELECT id FROM optimization_runs ORDER BY id DESC LIMIT 1
        )
        SELECT p2.instance_name, p2.block_reason, p2.phase2_action_reason, p2.created_at
        FROM phase2_ec2_outputs p2
        JOIN latest_run r ON r.id = p2.run_id
        WHERE p2.block_reason IS NOT NULL OR p2.action IN ('SKIP', 'REVIEW')
        ORDER BY p2.created_at DESC
        LIMIT ${limit}
      `,
      sql`
        WITH latest_run AS (
          SELECT id FROM optimization_runs ORDER BY id DESC LIMIT 1
        )
        SELECT COALESCE(res.name, 'resource-' || w.resource_id::text) AS resource,
               w.phase3_created_at AS created_at
        FROM waste w
        JOIN latest_run r ON r.id = w.run_id
        LEFT JOIN resources res ON res.id = w.resource_id
        WHERE w.parse_error IS NOT NULL
        LIMIT ${limit}
      `,
      sql`
        WITH latest_run AS (
          SELECT id FROM optimization_runs ORDER BY id DESC LIMIT 1
        )
        SELECT sw.bucket_name AS resource, sw.phase3_created_at AS created_at
        FROM s3_waste sw
        JOIN latest_run r ON r.id = sw.run_id
        WHERE sw.parse_error IS NOT NULL
        LIMIT ${limit}
      `,
    ]);

    type RawAlert = { ts: Date | null; severity: string; type: string; message: string; resource: string; };
    const alerts: RawAlert[] = [];

    for (const row of failedRuns) {
      alerts.push({
        ts: row.started_at as Date | null,
        severity: 'Critical',
        type: 'Pipeline failure',
        message: (row.error_message as string | null) ?? `Run ${row.id} ended with status ${row.status}.`,
        resource: `Run ${row.id}`,
      });
    }

    for (const row of blockedGuardrails) {
      alerts.push({
        ts: row.created_at as Date | null,
        severity: 'High',
        type: 'Guardrail block',
        message: ((row.block_reason ?? row.phase2_action_reason) as string | null)
          ?? 'A recommendation requires manual review.',
        resource: (row.instance_name as string | null) ?? 'Unknown',
      });
    }

    for (const row of [...ec2ParseErrors, ...s3ParseErrors]) {
      alerts.push({
        ts: row.created_at as Date | null,
        severity: 'Warning',
        type: 'Phase 3 parse error',
        message: 'Phase 3 LLM output could not be parsed.',
        resource: (row.resource as string | null) ?? 'Unknown',
      });
    }

    alerts.sort((a, b) => {
      const ta = a.ts?.getTime() ?? -Infinity;
      const tb = b.ts?.getTime() ?? -Infinity;
      return tb - ta;
    });

    return NextResponse.json(
      alerts.slice(0, limit).map(a => ({
        severity: a.severity,
        type: a.type,
        message: a.message,
        resource: a.resource,
        createdAt: a.ts?.toISOString() ?? null,
      }))
    );
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
