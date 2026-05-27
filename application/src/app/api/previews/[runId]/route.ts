import { NextResponse } from 'next/server';
import { getLatestPreview } from '@/lib/phase3-preview';

export async function GET(_req: Request, { params }: { params: Promise<{ runId: string }> }) {
  const { runId: runIdStr } = await params;
  const runId = parseInt(runIdStr, 10);
  if (isNaN(runId)) return NextResponse.json({ error: 'invalid runId' }, { status: 400 });

  try {
    const preview = await getLatestPreview(runId);
    return NextResponse.json({ preview });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
