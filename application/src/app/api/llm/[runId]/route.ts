import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';
import { MOCK_RUN_ID, mockLlm } from '@/lib/mock-run';

export async function GET(_req: Request, { params }: { params: Promise<{ runId: string }> }) {
  const { runId: runIdStr } = await params;
  const runId = parseInt(runIdStr, 10);
  if (isNaN(runId)) return NextResponse.json({ error: 'invalid runId' }, { status: 400 });
  if (runId === MOCK_RUN_ID) return NextResponse.json(mockLlm);

  try {
    const [ec2Waste, s3Waste] = await Promise.all([
      sql`SELECT w.*, r.name AS resource_name
          FROM waste w
          LEFT JOIN resources r ON r.id = w.resource_id
          WHERE w.run_id = ${runId}
          ORDER BY w.id`,

      sql`SELECT * FROM s3_waste
          WHERE run_id = ${runId}
          ORDER BY id`,
    ]);

    return NextResponse.json({ ec2Waste, s3Waste });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
