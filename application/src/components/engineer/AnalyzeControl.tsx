'use client';
import { useEffect, useState } from 'react';

interface Step {
  name: string;
  status: string;
  message: string | null;
  started_at: string | null;
  completed_at: string | null;
}

interface AnalysisState {
  status: string;
  pid?: number;
  run_id: number | string | null;
  started_at: string | null;
  completed_at: string | null;
  steps: Step[];
  error: string | null;
}

interface AnalysisResponse {
  state: AnalysisState | null;
  log: string;
  running: boolean;
}

const STEP_LABEL: Record<string, string> = {
  ingestion: 'Ingestion',
  phase1_phase2: 'Phase 1 + Phase 2',
  phase3_preview: 'Phase 3 + Preview',
  replay_fixture: 'Replay Mock',
};

const STATUS_STYLE: Record<string, string> = {
  running: 'bg-blue-900/60 text-blue-200',
  completed: 'bg-green-900/60 text-green-200',
  warning: 'bg-yellow-900/60 text-yellow-200',
  failed: 'bg-red-900/60 text-red-200',
  starting: 'bg-blue-900/60 text-blue-200',
};

function badge(status: string) {
  return STATUS_STYLE[status] ?? 'bg-gray-800 text-gray-300';
}

export default function AnalyzeControl({ onRunCreated }: { onRunCreated: () => void }) {
  const [data, setData] = useState<AnalysisResponse | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    const res = await fetch('/api/analyze', { cache: 'no-store' });
    const next = await res.json();
    setData(next);
    if (next?.state?.run_id) onRunCreated();
  }

  async function start() {
    setBusy(true);
    setExpanded(true);
    try {
      const res = await fetch('/api/analyze', { method: 'POST' });
      setData(await res.json());
    } finally {
      setBusy(false);
    }
  }

  async function replay() {
    setBusy(true);
    setExpanded(true);
    try {
      const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: 'replay' }),
      });
      const next = await res.json();
      setData(next);
      if (next?.state?.run_id) onRunCreated();
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    if (!data?.running && data?.state?.status !== 'starting') return;
    const timer = setInterval(refresh, 3000);
    return () => clearInterval(timer);
  }, [data?.running, data?.state?.status]);

  const state = data?.state;
  const disabled = busy || data?.running || state?.status === 'starting';

  return (
    <div className="border border-gray-800 bg-gray-900 rounded-xl p-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-white font-semibold">Analysis Run</h2>
            {state?.status && (
              <span className={`px-2 py-0.5 rounded text-xs font-medium ${badge(state.status)}`}>
                {state.status}
              </span>
            )}
          </div>
          <p className="text-gray-500 text-xs mt-1">
            {state?.run_id ? `Latest triggered run #${state.run_id}` : 'Start a fresh backend pass from the dashboard.'}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={start}
            disabled={disabled}
            className="px-4 py-2 rounded-lg bg-purple-700 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-purple-600 transition-colors"
          >
            {disabled ? 'Analysis running...' : 'Analyze'}
          </button>
          <button
            onClick={replay}
            disabled={disabled}
            className="px-4 py-2 rounded-lg bg-gray-800 text-gray-100 text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-gray-700 transition-colors"
          >
            Replay mock
          </button>
          <button
            onClick={() => setExpanded(open => !open)}
            className="px-3 py-2 rounded-lg bg-gray-800 text-gray-200 text-sm hover:bg-gray-700 transition-colors"
          >
            {expanded ? 'Hide output' : 'Show output'}
          </button>
        </div>
      </div>

      {!!state?.steps?.length && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-4">
          {state.steps.map(step => (
            <div key={step.name} className="border border-gray-800 rounded-lg p-3 bg-gray-950/50">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm text-white">{STEP_LABEL[step.name] ?? step.name}</span>
                <span className={`px-2 py-0.5 rounded text-xs ${badge(step.status)}`}>{step.status}</span>
              </div>
              {step.message && <p className="text-xs text-gray-400 mt-2">{step.message}</p>}
            </div>
          ))}
        </div>
      )}

      {state?.error && (
        <div className="mt-4 p-3 rounded-lg border border-red-900 bg-red-950/30 text-red-200 text-xs">
          {state.error}
        </div>
      )}

      {expanded && (
        <pre className="mt-4 max-h-80 overflow-auto rounded-lg border border-gray-800 bg-black p-3 text-xs text-gray-300 whitespace-pre-wrap">
          {data?.log || 'No output yet.'}
        </pre>
      )}
    </div>
  );
}
