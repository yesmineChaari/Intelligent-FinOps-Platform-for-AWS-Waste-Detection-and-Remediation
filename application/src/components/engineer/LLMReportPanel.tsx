'use client';
import { useState } from 'react';

interface WasteRow {
  id: number;
  resource_name: string | null;
  waste_type: string;
  verdict: string | null;
  decision_action: string | null;
  decided_by: string | null;
  decision_rationale: string | null;
  technical_explanation: string | null;
  cost_report: Record<string, unknown> | null;
  risk_assessment: Record<string, unknown> | null;
  terraform_action: string | null;
  terraform_block: string | null;
  parse_error: string | null;
}

interface S3WasteRow {
  id: number;
  bucket_name: string | null;
  waste_type: string;
  verdict: string | null;
  decision_action: string | null;
  technical_explanation: string | null;
  cost_report: Record<string, unknown> | null;
  terraform_block: string | null;
  parse_error: string | null;
}

const CARD_BORDER: Record<string, string> = {
  APPROVE: 'border-green-700 bg-green-950/30',
  BLOCK:   'border-red-700 bg-red-950/30',
  REVIEW:  'border-yellow-700 bg-yellow-950/30',
};

const VERDICT_BADGE: Record<string, string> = {
  APPROVE: 'bg-green-900 text-green-300 border border-green-700',
  BLOCK:   'bg-red-900 text-red-300 border border-red-700',
  REVIEW:  'bg-yellow-900 text-yellow-300 border border-yellow-700',
};

function TerraformBlock({ code }: { code: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-3">
      <button
        onClick={() => setOpen(p => !p)}
        className="flex items-center gap-1.5 text-xs text-purple-400 hover:text-purple-300 transition-colors"
      >
        <span className="text-[10px]">{open ? '▼' : '▶'}</span>
        {open ? 'Hide' : 'Show'} Terraform patch
      </button>
      {open && (
        <pre className="mt-2 p-4 bg-gray-950 border border-gray-700 rounded-lg text-xs text-green-300
                        overflow-x-auto max-h-72 whitespace-pre-wrap font-mono leading-relaxed">
          {code}
        </pre>
      )}
    </div>
  );
}

function KVGrid({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
      {Object.entries(data).map(([k, v]) => (
        <div key={k}>
          <span className="text-gray-500">{k.replace(/_/g, ' ')}: </span>
          <span className="text-gray-200">
            {typeof v === 'number' ? `$${v.toFixed(2)}` : String(v)}
          </span>
        </div>
      ))}
    </div>
  );
}

function ResourceCard({ row }: { row: WasteRow }) {
  const verdict     = row.verdict?.toUpperCase() ?? '';
  const borderClass = CARD_BORDER[verdict] ?? 'border-gray-700 bg-gray-900/50';
  const badgeClass  = VERDICT_BADGE[verdict];

  return (
    <div className={`border rounded-xl p-5 ${borderClass}`}>
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <p className="text-white font-mono text-sm">{row.resource_name ?? `#${row.id}`}</p>
          <p className="text-gray-500 text-xs mt-0.5">{row.waste_type}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {badgeClass && (
            <span className={`px-2.5 py-1 rounded text-xs font-bold ${badgeClass}`}>{verdict}</span>
          )}
          {row.decision_action && (
            <span className="px-2 py-1 rounded text-xs bg-gray-800 text-gray-300">{row.decision_action}</span>
          )}
        </div>
      </div>

      {row.technical_explanation && (
        <div className="mb-3">
          <p className="text-gray-500 text-xs uppercase tracking-wide font-medium mb-1">Technical analysis</p>
          <p className="text-gray-300 text-sm leading-relaxed">{row.technical_explanation}</p>
        </div>
      )}

      {row.decision_rationale && (
        <div className="mb-3">
          <p className="text-gray-500 text-xs uppercase tracking-wide font-medium mb-1">Rationale</p>
          <p className="text-gray-400 text-sm">{row.decision_rationale}</p>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {row.cost_report && Object.keys(row.cost_report).length > 0 && (
          <div className="p-3 bg-gray-900 rounded-lg">
            <p className="text-gray-500 text-xs uppercase tracking-wide font-medium mb-2">Cost report</p>
            <KVGrid data={row.cost_report} />
          </div>
        )}
        {row.risk_assessment && Object.keys(row.risk_assessment).length > 0 && (
          <div className="p-3 bg-gray-900 rounded-lg">
            <p className="text-gray-500 text-xs uppercase tracking-wide font-medium mb-2">Risk assessment</p>
            <KVGrid data={row.risk_assessment} />
          </div>
        )}
      </div>

      {row.terraform_action && (
        <p className="mt-3 text-xs text-gray-500">
          Terraform action: <span className="text-purple-400">{row.terraform_action}</span>
          {row.decided_by && <span className="ml-2 text-gray-600">· by {row.decided_by}</span>}
        </p>
      )}

      {row.terraform_block && <TerraformBlock code={row.terraform_block} />}

      {row.parse_error && (
        <div className="mt-3 p-2 bg-red-950 border border-red-800 rounded text-xs text-red-300">
          Parse error: {row.parse_error}
        </div>
      )}
    </div>
  );
}

function S3Card({ row }: { row: S3WasteRow }) {
  const verdict     = row.verdict?.toUpperCase() ?? '';
  const borderClass = CARD_BORDER[verdict] ?? 'border-gray-700 bg-gray-900/50';
  const badgeClass  = VERDICT_BADGE[verdict];

  return (
    <div className={`border rounded-xl p-5 ${borderClass}`}>
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <p className="text-white font-mono text-sm">{row.bucket_name}</p>
          <p className="text-gray-500 text-xs mt-0.5">{row.waste_type}</p>
        </div>
        {badgeClass && (
          <span className={`px-2.5 py-1 rounded text-xs font-bold shrink-0 ${badgeClass}`}>{verdict}</span>
        )}
      </div>

      {row.technical_explanation && (
        <p className="text-gray-300 text-sm leading-relaxed mb-3">{row.technical_explanation}</p>
      )}

      {row.cost_report && Object.keys(row.cost_report).length > 0 && (
        <div className="p-3 bg-gray-900 rounded-lg mb-3">
          <p className="text-gray-500 text-xs uppercase tracking-wide font-medium mb-2">Cost report</p>
          <KVGrid data={row.cost_report} />
        </div>
      )}

      {row.terraform_block && <TerraformBlock code={row.terraform_block} />}

      {row.parse_error && (
        <div className="mt-3 p-2 bg-red-950 border border-red-800 rounded text-xs text-red-300">
          Parse error: {row.parse_error}
        </div>
      )}
    </div>
  );
}

export default function LLMReportPanel({
  ec2Waste,
  s3Waste,
}: {
  ec2Waste: WasteRow[];
  s3Waste: S3WasteRow[];
}) {
  if (!ec2Waste.length && !s3Waste.length) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-10 text-center">
        <p className="text-gray-400">No LLM analysis for this run</p>
        <p className="text-gray-600 text-xs mt-1">Enable Phase 3 by setting PHASE3_MODEL in your .env</p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {ec2Waste.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-4">
            <span className="w-2 h-2 rounded-full bg-blue-500" />
            <h3 className="text-white font-semibold">EC2 Analysis</h3>
            <span className="text-gray-500 text-xs">({ec2Waste.length})</span>
          </div>
          <div className="space-y-4">
            {ec2Waste.map(row => <ResourceCard key={row.id} row={row} />)}
          </div>
        </div>
      )}

      {s3Waste.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-4">
            <span className="w-2 h-2 rounded-full bg-teal-500" />
            <h3 className="text-white font-semibold">S3 Analysis</h3>
            <span className="text-gray-500 text-xs">({s3Waste.length})</span>
          </div>
          <div className="space-y-4">
            {s3Waste.map(row => <S3Card key={row.id} row={row} />)}
          </div>
        </div>
      )}
    </div>
  );
}
