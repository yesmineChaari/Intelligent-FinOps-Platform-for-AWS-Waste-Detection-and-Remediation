import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';

export async function GET() {
  try {
    const [summaryRows, wasteBreakdown, trendRows] = await Promise.all([
      sql`
        SELECT
          COALESCE((SELECT SUM(waste_per_month) FROM phase1_ec2_outputs), 0)::numeric        AS ec2_savings,
          COALESCE((SELECT SUM((metrics->>'estimated_monthly_savings')::numeric)
                    FROM phase1_s3_outputs), 0)::numeric                                     AS s3_savings,
          (SELECT COUNT(*) FROM optimization_runs WHERE status = 'completed')::int           AS completed_runs,
          (SELECT COUNT(*) FROM optimization_runs)::int                                      AS total_runs,
          (SELECT COUNT(*) FROM phase1_ec2_outputs)::int                                     AS ec2_flagged,
          (SELECT COUNT(*) FROM phase1_s3_outputs)::int                                      AS s3_flagged,
          (
            SELECT COUNT(*) FROM phase2_ec2_outputs p2
            WHERE p2.run_id = (SELECT id FROM optimization_runs ORDER BY id DESC LIMIT 1)
              AND (p2.block_reason IS NOT NULL OR p2.action IN ('SKIP', 'REVIEW'))
          )::int                                                                              AS blocked_count
      `,
      sql`
        SELECT
          waste_type,
          action,
          COUNT(*)::int                              AS count,
          COALESCE(SUM(waste_per_month), 0)::numeric AS total_savings
        FROM phase1_ec2_outputs
        GROUP BY waste_type, action
        ORDER BY total_savings DESC
      `,
      sql`
        SELECT
          run.id,
          run.started_at,
          (
            COALESCE(
              (SELECT SUM(p2.waste_per_month) FROM phase2_ec2_outputs p2 WHERE p2.run_id = run.id),
              (SELECT SUM(p1.waste_per_month) FROM phase1_ec2_outputs p1 WHERE p1.run_id = run.id),
              0
            )
            +
            COALESCE(
              (SELECT SUM((p1s.metrics->>'estimated_monthly_savings')::numeric)
               FROM phase1_s3_outputs p1s WHERE p1s.run_id = run.id),
              0
            )
          )::numeric AS savings
        FROM optimization_runs run
        WHERE run.status = 'completed'
        ORDER BY run.id DESC
        LIMIT 6
      `,
    ]);

    const trend = [...trendRows].reverse().map((r: any) => ({
      label: new Date(r.started_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
      savings: Number(r.savings),
    }));

    return NextResponse.json({ summary: summaryRows[0], wasteBreakdown, trend });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
