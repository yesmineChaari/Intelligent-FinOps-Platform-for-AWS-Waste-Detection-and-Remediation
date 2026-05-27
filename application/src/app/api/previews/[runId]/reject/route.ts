import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';
import { getLatestPreview } from '@/lib/phase3-preview';

export async function POST(req: Request, { params }: { params: Promise<{ runId: string }> }) {
  const { runId: runIdStr } = await params;
  const runId = parseInt(runIdStr, 10);
  if (isNaN(runId)) return NextResponse.json({ error: 'invalid runId' }, { status: 400 });

  const body = await req.json().catch(() => ({}));
  const rejectedBy = typeof body?.rejectedBy === 'string' ? body.rejectedBy.slice(0, 120) : 'dashboard_user';
  const note = typeof body?.note === 'string' ? body.note.slice(0, 1000) : null;

  try {
    const preview = await getLatestPreview(runId);
    if (!preview) return NextResponse.json({ error: 'No patch preview found for this run.' }, { status: 404 });
    if (preview.status === 'pr_created') {
      return NextResponse.json({ error: 'A pull request has already been created for this preview.' }, { status: 409 });
    }

    const rows = await sql`
      UPDATE phase3_patch_previews
      SET status = 'rejected',
          rejected_by = ${rejectedBy},
          approval_note = ${note},
          rejected_at = NOW(),
          updated_at = NOW()
      WHERE id = ${preview.id}
      RETURNING *
    `;
    return NextResponse.json({ preview: rows[0] });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
