interface Run {
  id: number;
  workspace_key: string | null;
  status: string;
  started_at: string;
}

interface Props {
  runs: Run[];
  selectedId: number | null;
  onChange: (id: number) => void;
}

export default function RunSelector({ runs, selectedId, onChange }: Props) {
  return (
    <div className="flex items-center gap-3 flex-wrap">
      <label className="text-gray-400 text-sm shrink-0">Optimization Run</label>
      <select
        value={selectedId ?? ''}
        onChange={e => onChange(Number(e.target.value))}
        className="bg-gray-800 border border-gray-700 text-white rounded-lg px-3 py-2 text-sm
                   focus:outline-none focus:ring-2 focus:ring-purple-500 min-w-64"
      >
        <option value="">Select a run…</option>
        {runs.map(r => (
          <option key={r.id} value={r.id}>
            Run #{r.id} — {new Date(r.started_at).toLocaleDateString('en-US', {
              month: 'short', day: 'numeric', year: 'numeric',
            })} ({r.status}){r.workspace_key ? ` · ${r.workspace_key}` : ''}
          </option>
        ))}
      </select>
    </div>
  );
}
