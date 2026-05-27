import { NextResponse } from 'next/server';
import { getLatestPreview } from '@/lib/phase3-preview';
import { MOCK_RUN_ID, getMockPreview } from '@/lib/mock-run';

export async function GET(_req: Request, { params }: { params: Promise<{ runId: string }> }) {
  const { runId: runIdStr } = await params;
  const runId = parseInt(runIdStr, 10);
  if (isNaN(runId)) return NextResponse.json({ error: 'invalid runId' }, { status: 400 });
  if (runId === MOCK_RUN_ID) return NextResponse.json({ preview: getMockPreview() });

  try {
    const preview = await getLatestPreview(runId);
    return NextResponse.json({ preview });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
