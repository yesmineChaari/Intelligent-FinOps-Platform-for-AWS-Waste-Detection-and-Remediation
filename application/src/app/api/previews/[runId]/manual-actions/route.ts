import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';
import { getLatestPreview, type PreviewFile } from '@/lib/phase3-preview';
import { MOCK_RUN_ID, getMockPreview, mockLlm, setMockPreview } from '@/lib/mock-run';

export const runtime = 'nodejs';

type WasteRow = {
  id: number;
  resource_name: string | null;
  decision_action: string | null;
  action: string | null;
  scenario_json: any;
};

type Selection = {
  wasteId: number;
  targetType: string;
};

function firstResource(row: WasteRow) {
  const resources = row.scenario_json?.flagged_resources;
  return Array.isArray(resources) ? resources[0] : null;
}

function moduleBounds(content: string, instanceId: string) {
  const pattern = /(^[ \t]*module\s+"[^"]+"\s*\{)/gm;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(content)) !== null) {
    const start = match.index;
    const open = content.indexOf('{', pattern.lastIndex - 1);
    if (open < 0) continue;

    let depth = 0;
    let inString = false;
    let escaped = false;
    let lineComment = false;
    for (let index = open; index < content.length; index += 1) {
      const char = content[index];
      const next = content[index + 1] ?? '';

      if (lineComment) {
        if (char === '\n' || char === '\r') lineComment = false;
        continue;
      }
      if (inString) {
        if (escaped) escaped = false;
        else if (char === '\\') escaped = true;
        else if (char === '"') inString = false;
        continue;
      }

      if (char === '#') {
        lineComment = true;
        continue;
      }
      if (char === '/' && next === '/') {
        lineComment = true;
        continue;
      }
      if (char === '"') {
        inString = true;
        continue;
      }
      if (char === '{') depth += 1;
      if (char === '}') {
        depth -= 1;
        if (depth === 0) {
          const end = index + 1;
          const block = content.slice(start, end);
          if (new RegExp(`^[ \\t]*instance_id\\s*=\\s*"${escapeRegExp(instanceId)}"`, 'm').test(block)) {
            return { start, end, block };
          }
          break;
        }
      }
    }
  }
  return null;
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function patchInstanceType(content: string, instanceId: string, newType: string) {
  const bounds = moduleBounds(content, instanceId);
  if (!bounds) throw new Error(`Could not find Terraform module for ${instanceId}.`);

  if (new RegExp(`^[ \\t]*instance_type\\s*=\\s*"${escapeRegExp(newType)}"`, 'm').test(bounds.block)) {
    return content;
  }

  const patchedBlock = bounds.block.replace(
    /^([ \t]*instance_type\s*=\s*)"([^"]+)"/m,
    `$1"${newType}"`,
  );
  if (patchedBlock === bounds.block) {
    throw new Error(`Could not replace instance_type for ${instanceId}.`);
  }
  return content.slice(0, bounds.start) + patchedBlock + content.slice(bounds.end);
}

function asPreviewFiles(value: unknown): PreviewFile[] {
  return Array.isArray(value) ? value as PreviewFile[] : [];
}

export async function POST(req: Request, { params }: { params: Promise<{ runId: string }> }) {
  const { runId: runIdStr } = await params;
  const runId = parseInt(runIdStr, 10);
  if (isNaN(runId)) return NextResponse.json({ error: 'invalid runId' }, { status: 400 });

  const body = await req.json().catch(() => ({}));
  const selections: Selection[] = Array.isArray(body?.selections)
    ? body.selections
        .map((item: any) => ({
          wasteId: Number(item?.wasteId),
          targetType: String(item?.targetType || '').trim(),
        }))
        .filter((item: Selection) => Number.isFinite(item.wasteId) && item.targetType)
    : [];
  const ids = selections.length
    ? selections.map(item => item.wasteId)
    : Array.isArray(body?.wasteIds)
    ? body.wasteIds.map((id: unknown) => Number(id)).filter(Number.isFinite)
    : [];
  if (!ids.length) return NextResponse.json({ error: 'No decision ids selected.' }, { status: 400 });
  const targetById = new Map(selections.map(item => [item.wasteId, item.targetType]));
  if (runId === MOCK_RUN_ID) {
    const preview = getMockPreview();
    const files = asPreviewFiles(preview.modified_files);
    const main = files.find(file => file.file_path === 'main.tf');
    let nextContent = main?.new_content ?? '';
    const added = mockLlm.ec2Waste
      .map(row => {
        const resource = firstResource(row);
        const target = targetById.get(row.id);
        const currentType = resource?.instance_type;
        const instanceId = resource?.instance_id || row.resource_name;
        if (!target || !currentType || target === currentType) return null;
        if (nextContent && instanceId) {
          nextContent = patchInstanceType(nextContent, String(instanceId), String(target));
        }
        return `${instanceId}: ${currentType} -> ${target}`;
      })
      .filter((line): line is string => Boolean(line));
    const nextPreview = setMockPreview({
      ...preview,
      modified_files: files.map(file => file.file_path === 'main.tf' ? { ...file, new_content: nextContent } : file),
      updated_at: new Date().toISOString(),
      pr_description: added.length
        ? `Mock selected EC2 resize changes:\n${added.map(line => `- ${line}`).join('\n')}`
        : preview.pr_description,
    });
    return NextResponse.json({
      preview: nextPreview,
      added,
      warnings: nextPreview.warnings,
    });
  }

  try {
    const preview = await getLatestPreview(runId);
    if (!preview) return NextResponse.json({ error: 'No base preview found for this run.' }, { status: 404 });
    if (!['pending', 'pr_failed'].includes(preview.status)) {
      return NextResponse.json({ error: `Preview status is ${preview.status}; it cannot be edited.` }, { status: 409 });
    }

    const rows = await sql`
      SELECT w.id, r.name AS resource_name, w.action, w.decision_action, w.scenario_json
      FROM waste w
      LEFT JOIN resources r ON r.id = w.resource_id
      WHERE w.run_id = ${runId}
        AND w.id = ANY(${ids}::bigint[])
      ORDER BY w.id
    ` as WasteRow[];

    const files = asPreviewFiles(preview.modified_files);
    const main = files.find(file => file.file_path === 'main.tf');
    if (!main) return NextResponse.json({ error: 'Preview does not contain main.tf.' }, { status: 409 });

    let nextContent = main.new_content;
    const added: string[] = [];
    const warnings = [...(preview.warnings ?? [])];

    for (const row of rows) {
      const action = String(row.decision_action || row.action || '').toUpperCase();
      const resource = firstResource(row);
      const instanceId = resource?.instance_id || row.resource_name;
      const currentType = resource?.instance_type;
      const recommendedType = targetById.get(Number(row.id)) || resource?.agent2_decision?.recommended_type;

      if (!['DOWNSIZE', 'REVIEW'].includes(action)) {
        warnings.push(`${instanceId}: ${action} requires an operational approval workflow, not an instance_type preview patch.`);
        continue;
      }
      if (!instanceId || !currentType || !recommendedType) {
        warnings.push(`${instanceId || row.id}: ${action} has no concrete instance_type recommendation to patch.`);
        continue;
      }
      if (String(recommendedType) === String(currentType)) {
        continue;
      }

      nextContent = patchInstanceType(nextContent, String(instanceId), String(recommendedType));
      added.push(`${instanceId}: ${currentType} -> ${recommendedType}`);
    }

    if (!added.length) {
      return NextResponse.json({ error: 'No selected decisions could be converted into Terraform preview changes.', warnings }, { status: 409 });
    }

    const nextFiles = files.map(file => file.file_path === 'main.tf' ? { ...file, new_content: nextContent } : file);
    const description = `User-selected EC2 resize changes:\n${added.map(line => `- ${line}`).join('\n')}`;

    const updated = await sql`
      UPDATE phase3_patch_previews
      SET modified_files = ${JSON.stringify(nextFiles)}::jsonb,
          warnings = ${JSON.stringify(warnings)}::jsonb,
          pr_description = ${description},
          status = 'pending',
          updated_at = NOW()
      WHERE id = ${preview.id}
      RETURNING *
    `;

    return NextResponse.json({ preview: updated[0], added, warnings });
  } catch (error) {
    return NextResponse.json({ error: String(error) }, { status: 500 });
  }
}
