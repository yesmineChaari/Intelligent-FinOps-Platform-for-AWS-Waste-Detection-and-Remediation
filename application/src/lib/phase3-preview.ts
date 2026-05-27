import { sql } from '@/lib/db';

export interface PreviewFile {
  file_path: string;
  original_content: string | null;
  original_content_available?: boolean;
  new_content: string;
}

export interface PatchPreviewRow {
  id: number;
  run_id: number;
  source_repo_url: string | null;
  source_ref: string | null;
  source_subdir: string | null;
  pr_title: string | null;
  pr_description: string | null;
  status: string;
  modified_files: PreviewFile[];
  warnings: string[];
  validation_errors: string[];
  approval_note: string | null;
  approved_by: string | null;
  rejected_by: string | null;
  branch_name: string | null;
  pr_url: string | null;
  pr_errors: string[];
  created_at: string;
  updated_at: string;
  approved_at: string | null;
  rejected_at: string | null;
}

function cleanEnv(value: string | undefined) {
  return (value ?? '').trim().replace(/^['"]|['"]$/g, '');
}

function parseTerraformPromptBundle(bundle: string | null) {
  const files = new Map<string, string>();
  if (!bundle) return files;

  const pattern = /### FILE:\s*([^\n\r]+)\r?\n```(?:hcl|terraform|tf)?\r?\n([\s\S]*?)\r?\n```/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(bundle)) !== null) {
    files.set(match[1].trim(), match[2].replace(/\r?\n$/, ''));
  }
  return files;
}

function firstText(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return null;
}

function normalizeModifiedFiles(
  rawFiles: unknown,
  originalFiles: Map<string, string>,
): PreviewFile[] {
  if (!Array.isArray(rawFiles)) return [];
  const byPath = new Map<string, PreviewFile>();

  for (const item of rawFiles) {
    if (!item || typeof item !== 'object') continue;
    const file = item as Record<string, unknown>;
    const filePath = typeof file.file_path === 'string' ? file.file_path.trim() : '';
    const newContent = typeof file.new_content === 'string' ? file.new_content : '';
    if (!filePath || !newContent.trim()) continue;

    byPath.set(filePath, {
      file_path: filePath,
      original_content: originalFiles.get(filePath) ?? null,
      original_content_available: originalFiles.has(filePath),
      new_content: newContent,
    });
  }

  return Array.from(byPath.values());
}

export async function ensurePreviewTable() {
  await sql`
    CREATE TABLE IF NOT EXISTS phase3_patch_previews (
      id BIGSERIAL PRIMARY KEY,
      run_id BIGINT NOT NULL REFERENCES optimization_runs(id) ON DELETE CASCADE,
      source_repo_url TEXT,
      source_ref TEXT,
      source_subdir TEXT,
      pr_title TEXT,
      pr_description TEXT,
      status TEXT NOT NULL DEFAULT 'pending',
      modified_files JSONB NOT NULL DEFAULT '[]'::jsonb,
      warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
      validation_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
      approval_note TEXT,
      approved_by TEXT,
      rejected_by TEXT,
      branch_name TEXT,
      pr_url TEXT,
      pr_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      approved_at TIMESTAMPTZ,
      rejected_at TIMESTAMPTZ
    )
  `;
  await sql`CREATE INDEX IF NOT EXISTS phase3_patch_previews_run_idx ON phase3_patch_previews(run_id)`;
}

export async function getLatestPreview(runId: number) {
  await ensurePreviewTable();
  const rows = await sql`
    SELECT *
    FROM phase3_patch_previews
    WHERE run_id = ${runId}
    ORDER BY id DESC
    LIMIT 1
  `;
  if (rows[0]) return rows[0] as PatchPreviewRow;

  await createLegacyPreview(runId);

  const recoveredRows = await sql`
    SELECT *
    FROM phase3_patch_previews
    WHERE run_id = ${runId}
    ORDER BY id DESC
    LIMIT 1
  `;
  return (recoveredRows[0] ?? null) as PatchPreviewRow | null;
}

async function createLegacyPreview(runId: number) {
  const rows = await sql`
    WITH phase3_rows AS (
      SELECT id, run_id, llm_raw_output, scenario_json, phase3_created_at AS created_at
      FROM waste
      WHERE run_id = ${runId}
      UNION ALL
      SELECT id, run_id, llm_raw_output, scenario_json, phase3_created_at AS created_at
      FROM s3_waste
      WHERE run_id = ${runId}
    )
    SELECT llm_raw_output, scenario_json
    FROM phase3_rows
    WHERE jsonb_array_length(COALESCE(llm_raw_output->'parsed'->'modified_files', '[]'::jsonb)) > 0
    ORDER BY created_at DESC, id DESC
  `;

  if (!rows.length) return;

  const modifiedByPath = new Map<string, PreviewFile>();
  const warnings = ['Recovered from legacy Phase 3 LLM output; regenerate the run for a first-class preview.'];
  let title: string | null = null;
  let description: string | null = null;

  for (const row of rows as Array<{ llm_raw_output: any; scenario_json: any }>) {
    const parsed = row.llm_raw_output?.parsed;
    if (!parsed || typeof parsed !== 'object') continue;

    title = title ?? firstText(parsed.pr_title);
    description = description ?? firstText(parsed.pr_description);

    const originalFiles = parseTerraformPromptBundle(row.scenario_json?.current_terraform ?? null);
    for (const file of normalizeModifiedFiles(parsed.modified_files, originalFiles)) {
      modifiedByPath.set(file.file_path, file);
    }
  }

  const modifiedFiles = Array.from(modifiedByPath.values());
  if (!modifiedFiles.length) return;

  const repoUrl = cleanEnv(process.env.PHASE3_TERRAFORM_REPO_URL) || cleanEnv(process.env.GITHUB_REPO) || null;
  const ref = cleanEnv(process.env.PHASE3_TERRAFORM_REF) || null;

  await sql`
    INSERT INTO phase3_patch_previews (
      run_id,
      source_repo_url,
      source_ref,
      source_subdir,
      pr_title,
      pr_description,
      status,
      modified_files,
      warnings,
      validation_errors
    )
    VALUES (
      ${runId},
      ${repoUrl},
      ${ref},
      ${cleanEnv(process.env.PHASE3_TERRAFORM_SUBDIR) || null},
      ${title ?? 'Recovered Phase 3 Terraform preview'},
      ${description ?? 'Recovered from legacy Phase 3 LLM output.'},
      'pending',
      ${JSON.stringify(modifiedFiles)}::jsonb,
      ${JSON.stringify(warnings)}::jsonb,
      '[]'::jsonb
    )
  `;
}
