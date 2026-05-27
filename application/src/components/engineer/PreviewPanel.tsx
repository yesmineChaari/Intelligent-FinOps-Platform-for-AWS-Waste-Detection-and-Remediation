'use client';
import { useEffect, useMemo, useState } from 'react';
import ActionBadge from './ActionBadge';

interface PreviewFile {
  file_path: string;
  original_content: string | null;
  original_content_available?: boolean;
  new_content: string;
}

interface Preview {
  id: number;
  run_id: number;
  status: string;
  source_repo_url: string | null;
  source_ref: string | null;
  pr_title: string | null;
  pr_description: string | null;
  modified_files: PreviewFile[];
  warnings: string[];
  validation_errors: string[];
  approval_note: string | null;
  branch_name: string | null;
  pr_url: string | null;
  pr_errors: string[];
}

interface Ec2WasteRow {
  id: number;
  resource_name: string | null;
  action: string | null;
  decision_action: string | null;
  verdict: string | null;
  decided_by: string | null;
  decision_rationale: string | null;
  terraform_action: string | null;
  scenario_json?: any;
}

const DEFAULT_SIZE_ORDER = ['nano', 'micro', 'small', 'medium', 'large', 'xlarge', '2xlarge', '4xlarge', '8xlarge', '12xlarge', '16xlarge', '24xlarge', '32xlarge'];
const FAMILY_SIZE_ORDER: Record<string, string[]> = {
  c5: ['large', 'xlarge', '2xlarge', '4xlarge', '9xlarge', '12xlarge', '18xlarge', '24xlarge'],
  m5: ['large', 'xlarge', '2xlarge', '4xlarge', '8xlarge', '12xlarge', '16xlarge', '24xlarge'],
  r5: ['large', 'xlarge', '2xlarge', '4xlarge', '8xlarge', '12xlarge', '16xlarge', '24xlarge'],
};

function sizeOptions(currentType?: string | null, recommendedType?: string | null) {
  if (!currentType) return recommendedType ? [recommendedType] : [];
  const [family, size] = currentType.split('.');
  const familyOrder = FAMILY_SIZE_ORDER[family] || [];
  const familyIndex = familyOrder.indexOf(size);
  const genericIndex = DEFAULT_SIZE_ORDER.indexOf(size);
  const sizeOrder = familyIndex >= 2 || genericIndex < 0 ? familyOrder : DEFAULT_SIZE_ORDER;
  const index = sizeOrder.indexOf(size);
  const options: string[] = [currentType];
  if (index > 0) options.push(`${family}.${sizeOrder[index - 1]}`);
  if (index > 1) options.push(`${family}.${sizeOrder[index - 2]}`);
  if (options.length < 3 && recommendedType && !options.includes(recommendedType)) options.push(recommendedType);
  return options.slice(0, 3);
}

function rowResource(row: Ec2WasteRow) {
  const resources = row.scenario_json?.flagged_resources;
  return Array.isArray(resources) ? resources[0] : null;
}

function previewChangeLines(description?: string | null) {
  if (!description) return [];
  return description
    .split('\n')
    .map(line => line.trim())
    .filter(line => line.startsWith('- '))
    .map(line => line.slice(2));
}

function sliderTone(index: number) {
  if (index === 0) {
    return {
      badge: 'border-red-700 bg-red-950/70 text-red-100',
      accent: 'bg-red-500',
      border: 'border-red-500',
      text: 'text-red-300',
      label: 'Current',
    };
  }
  if (index === 1) {
    return {
      badge: 'border-orange-600 bg-orange-950/70 text-orange-100',
      accent: 'bg-orange-400',
      border: 'border-orange-400',
      text: 'text-orange-300',
      label: '1 size down',
    };
  }
  return {
    badge: 'border-green-700 bg-green-950/70 text-green-100',
    accent: 'bg-green-500',
    border: 'border-green-500',
    text: 'text-green-300',
    label: '2 sizes down',
  };
}

function ResizeSlider({
  options,
  value,
  onChange,
}: {
  options: string[];
  value: string;
  onChange: (value: string) => void;
}) {
  const selectedIndex = Math.max(0, options.indexOf(value));
  const tone = sliderTone(selectedIndex);
  const displayOptions = [...options].reverse();
  const displayIndex = Math.max(0, displayOptions.indexOf(value));

  return (
    <div className="w-40 shrink-0">
      <div className={`mb-3 rounded-lg border px-3 py-2 text-center ${tone.badge}`}>
        <p className="text-[10px] uppercase tracking-wide opacity-80">{tone.label}</p>
        <p className="mt-0.5 font-mono text-sm font-semibold">{value}</p>
      </div>
      <div className="relative px-1 py-5">
        <div className={`absolute left-4 right-4 top-1/2 h-1 -translate-y-1/2 rounded-full ${tone.accent}`} />
        <div className="relative flex items-center justify-between">
          {displayOptions.map(option => {
            const isSelected = option === value;
            return (
              <button
                key={option}
                type="button"
                onClick={() => onChange(option)}
                className={`h-5 w-5 rounded-full border-2 transition-all ${tone.border} ${
                  isSelected ? `${tone.accent} shadow-lg shadow-black/40` : 'bg-gray-950'
                }`}
                title={option}
                aria-label={`Select ${option}`}
              />
            );
          })}
        </div>
        <input
          type="range"
          min={0}
          max={Math.max(0, displayOptions.length - 1)}
          step={1}
          value={displayIndex}
          onChange={event => onChange(displayOptions[Number(event.target.value)] || displayOptions[0])}
          className="absolute inset-x-0 top-0 h-full opacity-0 cursor-pointer"
          aria-label="Choose instance size"
        />
      </div>
      <div className="flex justify-between gap-2 text-[10px] font-mono text-gray-500">
        {displayOptions.map(option => (
          <span key={option} className={option === value ? tone.text : undefined}>
            {option.split('.')[1] ?? option}
          </span>
        ))}
      </div>
    </div>
  );
}

export default function PreviewPanel({
  preview,
  ec2Waste = [],
  onRefresh,
}: {
  preview: Preview | null;
  ec2Waste?: Ec2WasteRow[];
  onRefresh: () => void;
}) {
  const [busy, setBusy] = useState<'approve' | 'reject' | 'manual' | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const resizeRows = useMemo(() => ec2Waste.filter(row => {
    const action = (row.decision_action || row.action || '').toUpperCase();
    const resource = rowResource(row);
    const options = sizeOptions(resource?.instance_type, resource?.agent2_decision?.recommended_type);
    return ['DOWNSIZE', 'REVIEW'].includes(action) && resource?.instance_type && options.length > 1;
  }), [ec2Waste]);
  const operationalRows = useMemo(() => ec2Waste.filter(row => {
    const action = (row.decision_action || row.action || '').toUpperCase();
    return ['STOP', 'TERMINATE'].includes(action);
  }), [ec2Waste]);
  const [selectedTypes, setSelectedTypes] = useState<Record<number, string>>({});

  useEffect(() => {
    const next: Record<number, string> = {};
    for (const row of resizeRows) {
      const action = (row.decision_action || row.action || '').toUpperCase();
      const resource = rowResource(row);
      const recommendedType = resource?.agent2_decision?.recommended_type;
      const options = sizeOptions(resource?.instance_type, recommendedType);
      next[row.id] = action === 'REVIEW'
        ? options[0] || ''
        : options[1] || options[0] || '';
    }
    setSelectedTypes(next);
  }, [resizeRows]);

  async function saveSizeChoices() {
    if (!preview) return;
    setBusy('manual');
    setMessage(null);
    try {
      const selections = resizeRows
        .map(row => ({ wasteId: row.id, targetType: selectedTypes[row.id] }))
        .filter(item => item.targetType);
      const res = await fetch(`/api/previews/${preview.run_id}/manual-actions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ selections }),
      });
      const data = await res.json();
      if (!res.ok) setMessage(data?.error ?? 'Could not update preview.');
      else setMessage(`Saved ${data?.added?.length ?? 0} resize choices.`);
      onRefresh();
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(null);
    }
  }

  async function approve() {
    if (!preview) return;
    setBusy('approve');
    setMessage(null);
    try {
      const res = await fetch(`/api/previews/${preview.run_id}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approvedBy: 'dashboard_user' }),
      });
      const data = await res.json();
      if (!res.ok) setMessage(data?.error ?? 'Approval failed.');
      else setMessage(data?.message ?? 'Pull request created.');
      onRefresh();
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(null);
    }
  }

  async function reject() {
    if (!preview) return;
    setBusy('reject');
    setMessage(null);
    try {
      const res = await fetch(`/api/previews/${preview.run_id}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rejectedBy: 'dashboard_user' }),
      });
      const data = await res.json();
      if (!res.ok) setMessage(data?.error ?? 'Reject failed.');
      else setMessage('Preview rejected.');
      onRefresh();
    } catch (error) {
      setMessage(String(error));
    } finally {
      setBusy(null);
    }
  }

  if (!preview) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-10 text-center">
        <p className="text-gray-400">No Terraform preview for this run</p>
        <p className="text-gray-600 text-xs mt-1">No successful backend preview is available for the selected run.</p>
      </div>
    );
  }

  const canApprove = ['pending', 'pr_failed'].includes(preview.status) && !preview.validation_errors?.length;
  const changeLines = previewChangeLines(preview.pr_description);

  return (
    <div className="space-y-5">
      {resizeRows.length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h3 className="text-white font-semibold">Resize Decisions</h3>
              <p className="text-gray-500 text-xs mt-1">
                Choose the target size for DOWNSIZE and REVIEW candidates.
              </p>
            </div>
            <span className="px-2 py-1 rounded text-xs font-medium bg-gray-800 text-gray-300">
              {resizeRows.length}
            </span>
          </div>
          <div className="mt-4 grid gap-4">
            {resizeRows.map(row => {
              const action = (row.decision_action || row.action || '').toUpperCase();
              const resource = rowResource(row);
              const currentType = resource?.instance_type;
              const recommendedType = resource?.agent2_decision?.recommended_type;
              const options = sizeOptions(currentType, recommendedType);
              const selected = selectedTypes[row.id] || options[0] || '';
              return (
                <div key={row.id} className="border border-gray-800 rounded-lg p-4 bg-gray-950/50">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <p className="font-mono text-sm text-white">{row.resource_name ?? `#${row.id}`}</p>
                        <ActionBadge action={action} />
                      </div>
                      <p className="mt-2 text-xs text-gray-400">
                        {resource?.agent2_decision?.detection_reason || row.decision_rationale || 'No detail available.'}
                      </p>
                      <div className="mt-3 flex flex-wrap gap-3 text-xs text-gray-400">
                        <span>Current <span className="text-white font-mono">{currentType}</span></span>
                        {recommendedType && <span>Suggested <span className="text-purple-300 font-mono">{recommendedType}</span></span>}
                      </div>
                    </div>
                    <ResizeSlider
                      options={options}
                      value={selected}
                      onChange={option => setSelectedTypes(prev => ({ ...prev, [row.id]: option }))}
                    />
                  </div>
                </div>
              );
            })}
          </div>
          <button
            onClick={saveSizeChoices}
            disabled={busy !== null || !preview}
            className="mt-4 px-4 py-2 rounded-lg bg-purple-700 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-purple-600 transition-colors"
          >
            {busy === 'manual' ? 'Saving choices...' : 'Save size choices'}
          </button>
        </div>
      )}

      {operationalRows.length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h3 className="text-white font-semibold">Operational Reminders</h3>
          <p className="text-gray-500 text-xs mt-1">
            STOP and TERMINATE are not shown as code changes in this workflow.
          </p>
          <div className="mt-4 grid gap-3">
            {operationalRows.map(row => {
              const action = (row.decision_action || row.action || '').toUpperCase();
              const text = action === 'STOP'
                ? 'Stop this instance through an approved EC2 stop operation/API call, then record the action.'
                : 'Terminate is destructive; handle through a separate explicit destructive-operation workflow or module-removal PR.';
              return (
                <div key={row.id} className="border border-gray-800 rounded-lg p-4 bg-gray-950/50">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-mono text-sm text-white">{row.resource_name ?? `#${row.id}`}</p>
                      <p className="mt-2 text-xs text-gray-400">{row.decision_rationale}</p>
                      <p className="mt-2 text-xs text-gray-300">{text}</p>
                    </div>
                    <ActionBadge action={action} className="py-1" />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div className="border-b border-gray-800 px-5 py-4 flex items-start justify-between gap-4">
          <div>
            <h3 className="text-white font-semibold">{preview.pr_title ?? 'Terraform Change Preview'}</h3>
            <p className="text-gray-500 text-xs mt-1 font-mono">
              {preview.source_repo_url ?? 'repository not configured'} {preview.source_ref ? `@ ${preview.source_ref}` : ''}
            </p>
          </div>
          <span className="px-2 py-1 rounded text-xs font-medium bg-gray-800 text-gray-300 uppercase">
            {preview.status}
          </span>
        </div>

        <div className="p-5">
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-gray-800 bg-gray-950/50 p-3">
              <p className="text-[10px] uppercase tracking-wide text-gray-500">Resize choices</p>
              <p className="mt-1 text-lg font-semibold text-white">{changeLines.length}</p>
            </div>
            <div className="rounded-lg border border-gray-800 bg-gray-950/50 p-3">
              <p className="text-[10px] uppercase tracking-wide text-gray-500">Files touched</p>
              <p className="mt-1 text-lg font-semibold text-white">{preview.modified_files?.length ?? 0}</p>
            </div>
            <div className="rounded-lg border border-gray-800 bg-gray-950/50 p-3">
              <p className="text-[10px] uppercase tracking-wide text-gray-500">Branch</p>
              <p className="mt-1 truncate font-mono text-xs text-gray-200">{preview.branch_name ?? 'created on approval'}</p>
            </div>
          </div>

          <div className="mt-4 rounded-lg border border-gray-800 bg-gray-950/40">
            <div className="border-b border-gray-800 px-4 py-3 flex items-center justify-between">
              <p className="text-sm font-medium text-white">Chosen EC2 resizes</p>
              <ActionBadge action="DOWNSIZE" />
            </div>
            {changeLines.length > 0 ? (
              <div className="divide-y divide-gray-800">
                {changeLines.map((line, index) => (
                  <div key={`${line}-${index}`} className="px-4 py-3 text-sm text-gray-300">
                    {line}
                  </div>
                ))}
              </div>
            ) : (
              <p className="px-4 py-5 text-sm text-gray-500">No resize choices saved yet.</p>
            )}
          </div>

          {!!preview.warnings?.length && (
            <div className="mt-4 p-3 border border-yellow-900 bg-yellow-950/30 rounded-lg text-xs text-yellow-200">
              {preview.warnings.map((warning, index) => <p key={index}>{warning}</p>)}
            </div>
          )}

          {!!preview.validation_errors?.length && (
            <div className="mt-4 p-3 border border-red-900 bg-red-950/30 rounded-lg text-xs text-red-200">
              {preview.validation_errors.map((error, index) => <p key={index}>{error}</p>)}
            </div>
          )}

          {!!preview.pr_errors?.length && (
            <div className="mt-4 p-3 border border-red-900 bg-red-950/30 rounded-lg text-xs text-red-200">
              {preview.pr_errors.map((error, index) => <p key={index}>{error}</p>)}
            </div>
          )}

          {preview.pr_url && (
            <a href={preview.pr_url} target="_blank" rel="noreferrer" className="inline-block mt-4 text-sm text-purple-300 hover:text-purple-200">
              {preview.pr_url}
            </a>
          )}

          <div className="mt-5 flex flex-wrap gap-3">
            <button
              onClick={approve}
              disabled={!canApprove || busy !== null}
              className="px-4 py-2 rounded-lg bg-green-700 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-green-600 transition-colors"
            >
              {busy === 'approve' ? 'Creating PR...' : 'Approve and create PR'}
            </button>
            <button
              onClick={reject}
              disabled={preview.status === 'pr_created' || busy !== null}
              className="px-4 py-2 rounded-lg bg-gray-800 text-gray-200 text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-gray-700 transition-colors"
            >
              {busy === 'reject' ? 'Rejecting...' : 'Reject'}
            </button>
          </div>
          {message && <p className="mt-3 text-xs text-gray-400">{message}</p>}
        </div>
      </div>
    </div>
  );
}
