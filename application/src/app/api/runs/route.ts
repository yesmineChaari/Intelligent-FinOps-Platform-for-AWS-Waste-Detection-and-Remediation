import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';
import { mockRun } from '@/lib/mock-run';

export async function GET() {
  try {
    const rows = await sql`
      SELECT
        r.id,
        r.workspace_key,
        r.status,
        r.started_at,
        r.completed_at,
        r.phase3_model_key,
        r.error_message,
        COUNT(DISTINCT p1e.id)::int                                                       AS ec2_count,
        COUNT(DISTINCT p1s.id)::int                                                       AS s3_count,
        COALESCE(SUM(p1e.waste_per_month), 0)::numeric                                    AS ec2_savings,
        COALESCE(SUM((p1s.metrics->>'estimated_monthly_savings')::numeric), 0)::numeric   AS s3_savings
      FROM optimization_runs r
      LEFT JOIN phase1_ec2_outputs p1e ON p1e.run_id = r.id
      LEFT JOIN phase1_s3_outputs  p1s ON p1s.run_id = r.id
      GROUP BY r.id, r.workspace_key, r.status, r.started_at, r.completed_at,
               r.phase3_model_key, r.error_message
      ORDER BY r.started_at DESC
      LIMIT 50
    `;
    return NextResponse.json([mockRun, ...rows]);
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
