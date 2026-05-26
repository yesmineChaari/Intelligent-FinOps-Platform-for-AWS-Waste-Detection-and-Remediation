import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';

export async function GET(_req: Request, { params }: { params: Promise<{ runId: string }> }) {
  const { runId: runIdStr } = await params;
  const runId = parseInt(runIdStr, 10);
  if (isNaN(runId)) return NextResponse.json({ error: 'invalid runId' }, { status: 400 });

  try {
    const [ec2Phase1, s3Phase1, ec2Phase2] = await Promise.all([
      sql`
        SELECT
          p1.id, p1.resource_id, p1.resource_name, p1.role,
          p1.action, p1.waste_type, p1.detection_window_days,
          p1.current_instance_type, p1.recommended_type,
          p1.current_cost_per_hour, p1.recommended_cost_per_hour,
          p1.waste_per_month, p1.detection_reason, p1.metrics, p1.created_at,
          inv.region,
          telemetry.avg_cpu,
          telemetry.avg_ram,
          telemetry.p95_cpu AS telemetry_p95_cpu
        FROM phase1_ec2_outputs p1
        LEFT JOIN ec2_instances inv ON inv.resource_id = p1.resource_id
        LEFT JOIN LATERAL (
          SELECT
            AVG(m.cpu_pct) FILTER (WHERE m.cpu_pct IS NOT NULL)                            AS avg_cpu,
            AVG(m.ram_pct) FILTER (WHERE m.ram_pct IS NOT NULL)                            AS avg_ram,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY m.cpu_pct)
              FILTER (WHERE m.cpu_pct IS NOT NULL)                                          AS p95_cpu
          FROM ec2_metrics m
          WHERE m.resource_id = p1.resource_id
        ) telemetry ON TRUE
        WHERE p1.run_id = ${runId}
        ORDER BY COALESCE(p1.waste_per_month, 0) DESC
      `,
      sql`
        SELECT
          p1s.id, p1s.resource_id, p1s.bucket_name,
          p1s.action, p1s.waste_type, p1s.detection_reason,
          p1s.recommended_action, p1s.metrics, p1s.lifecycle_policy_json, p1s.created_at,
          inv.region,
          inv.object_count AS inv_object_count,
          inv.size_bytes   AS inv_size_bytes
        FROM phase1_s3_outputs p1s
        LEFT JOIN s3_instances inv ON inv.resource_id = p1s.resource_id
        WHERE p1s.run_id = ${runId}
        ORDER BY (p1s.metrics->>'estimated_monthly_savings')::numeric DESC NULLS LAST
      `,
      sql`
        SELECT * FROM phase2_ec2_outputs
        WHERE run_id = ${runId}
        ORDER BY blast_radius DESC
      `,
    ]);

    return NextResponse.json({ ec2Phase1, s3Phase1, ec2Phase2 });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
