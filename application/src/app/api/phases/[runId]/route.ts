import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';

export async function GET(_req: Request, { params }: { params: Promise<{ runId: string }> }) {
  const { runId: runIdStr } = await params;
  const runId = parseInt(runIdStr, 10);
  if (isNaN(runId)) return NextResponse.json({ error: 'invalid runId' }, { status: 400 });

  try {
    const [ec2Phase1, s3Phase1, ec2Phase2] = await Promise.all([
      sql`SELECT * FROM phase1_ec2_outputs
          WHERE run_id = ${runId}
          ORDER BY COALESCE(waste_per_month, 0) DESC`,

      sql`SELECT * FROM phase1_s3_outputs
          WHERE run_id = ${runId}
          ORDER BY created_at`,

      sql`SELECT * FROM phase2_ec2_outputs
          WHERE run_id = ${runId}
          ORDER BY blast_radius DESC`,
    ]);

    return NextResponse.json({ ec2Phase1, s3Phase1, ec2Phase2 });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
