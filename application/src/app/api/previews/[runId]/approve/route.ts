import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';
import { createPullRequestFromPreview } from '@/lib/github-preview-pr';
import { getLatestPreview } from '@/lib/phase3-preview';
import { MOCK_RUN_ID, getMockPreview, setMockPreview } from '@/lib/mock-run';

export const runtime = 'nodejs';

export async function POST(req: Request, { params }: { params: Promise<{ runId: string }> }) {
  const { runId: runIdStr } = await params;
  const runId = parseInt(runIdStr, 10);
  if (isNaN(runId)) return NextResponse.json({ error: 'invalid runId' }, { status: 400 });

  const body = await req.json().catch(() => ({}));
  const approvedBy = typeof body?.approvedBy === 'string' ? body.approvedBy.slice(0, 120) : 'dashboard_user';
  const note = typeof body?.note === 'string' ? body.note.slice(0, 1000) : null;

  if (runId === MOCK_RUN_ID) {
    const preview = setMockPreview({
      ...getMockPreview(),
      status: 'mock_approved',
      approved_by: approvedBy,
      approval_note: note,
      approved_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      pr_errors: [],
    });
    return NextResponse.json({
      preview,
      message: 'Mock approval recorded; no GitHub pull request was created.',
    });
  }

  try {
    const preview = await getLatestPreview(runId);
    if (!preview) return NextResponse.json({ error: 'No patch preview found for this run.' }, { status: 404 });
    if (preview.validation_errors?.length) {
      return NextResponse.json({ error: 'Preview has validation errors and cannot be approved.' }, { status: 409 });
    }
    if (preview.status === 'pr_created') {
      return NextResponse.json({ preview });
    }
    if (!['pending', 'pr_failed'].includes(preview.status)) {
      return NextResponse.json({ error: `Preview status is ${preview.status}; it cannot be approved.` }, { status: 409 });
    }

    await sql`
      UPDATE phase3_patch_previews
      SET status = 'approving',
          approved_by = ${approvedBy},
          approval_note = ${note},
          approved_at = NOW(),
          updated_at = NOW(),
          pr_errors = '[]'::jsonb
      WHERE id = ${preview.id}
    `;

    try {
      const result = await createPullRequestFromPreview(preview);
      const rows = await sql`
        UPDATE phase3_patch_previews
        SET status = 'pr_created',
            branch_name = ${result.branchName},
            pr_url = ${result.prUrl},
            pr_errors = '[]'::jsonb,
            updated_at = NOW()
        WHERE id = ${preview.id}
        RETURNING *
      `;
      return NextResponse.json({ preview: rows[0], changedFiles: result.changedFiles });
    } catch (error) {
      const message = String(error);
      const rows = await sql`
        UPDATE phase3_patch_previews
        SET status = 'pr_failed',
            pr_errors = ${JSON.stringify([message])}::jsonb,
            updated_at = NOW()
        WHERE id = ${preview.id}
        RETURNING *
      `;
      return NextResponse.json({ error: message, preview: rows[0] }, { status: 500 });
    }
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
