import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';

export async function GET() {
  try {
    const [summary] = await sql`
      SELECT
        COALESCE((SELECT SUM(waste_per_month) FROM phase1_ec2_outputs), 0)::numeric        AS ec2_savings,
        COALESCE((SELECT SUM((metrics->>'estimated_monthly_savings')::numeric)
                  FROM phase1_s3_outputs), 0)::numeric                                     AS s3_savings,
        (SELECT COUNT(*) FROM optimization_runs WHERE status = 'completed')::int           AS completed_runs,
        (SELECT COUNT(*) FROM optimization_runs)::int                                      AS total_runs,
        (SELECT COUNT(*) FROM phase1_ec2_outputs)::int                                     AS ec2_flagged,
        (SELECT COUNT(*) FROM phase1_s3_outputs)::int                                      AS s3_flagged
    `;

    const wasteBreakdown = await sql`
      SELECT
        waste_type,
        action,
        COUNT(*)::int                           AS count,
        COALESCE(SUM(waste_per_month), 0)::numeric AS total_savings
      FROM phase1_ec2_outputs
      GROUP BY waste_type, action
      ORDER BY total_savings DESC
    `;

    return NextResponse.json({ summary, wasteBreakdown });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
