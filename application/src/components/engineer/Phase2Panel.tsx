import ActionBadge from './ActionBadge';

interface Phase2Row {
  id: number;
  instance_name: string | null;
  role: string | null;
  waste_type: string;
  phase1_action: string;
  action: string;
  phase2_action_changed: boolean;
  phase2_action_reason: string | null;
  blast_radius: number;
  relationship_count: number;
  blast_radius_explanation: string | null;
  waste_per_month: number | null;
  skip_write: boolean;
  block_reason: string | null;
}

function BlastBar({ score }: { score: number }) {
  const pct  = Math.min(score / 10, 1) * 100;
  const color = score === 0 ? 'bg-green-500' : score <= 2 ? 'bg-yellow-500' : 'bg-red-500';
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-400">{score}</span>
    </div>
  );
}

export default function Phase2Panel({ data }: { data: Phase2Row[] }) {
  if (!data?.length) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-8 text-center text-gray-500 text-sm">
        No Phase 2 guardrail data for this run
      </div>
    );
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      <div className="px-6 py-4 border-b border-gray-800 flex items-center justify-between">
        <h3 className="text-white font-semibold">Guardrail Decisions</h3>
        <span className="text-gray-500 text-xs">{data.length} instances</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800">
              <th className="text-left px-6 py-3 text-gray-400 font-medium">Instance</th>
              <th className="text-left px-6 py-3 text-gray-400 font-medium">Phase 1</th>
              <th className="text-left px-6 py-3 text-gray-400 font-medium">Final</th>
              <th className="text-left px-6 py-3 text-gray-400 font-medium">Blast radius</th>
              <th className="text-left px-6 py-3 text-gray-400 font-medium">Changed</th>
              <th className="text-left px-6 py-3 text-gray-400 font-medium">Reason</th>
            </tr>
          </thead>
          <tbody>
            {data.map(row => (
              <tr key={row.id} className="border-b border-gray-800/50 hover:bg-gray-800/20 transition-colors">
                <td className="px-6 py-4">
                  <div className="text-white font-mono text-xs">{row.instance_name ?? '—'}</div>
                  <div className="text-gray-500 text-xs mt-0.5">{row.role} · {row.waste_type}</div>
                </td>
                <td className="px-6 py-4"><ActionBadge action={row.phase1_action} /></td>
                <td className="px-6 py-4"><ActionBadge action={row.action} /></td>
                <td className="px-6 py-4"><BlastBar score={row.blast_radius} /></td>
                <td className="px-6 py-4">
                  {row.phase2_action_changed
                    ? <span className="text-yellow-400 text-xs font-medium">Yes</span>
                    : <span className="text-gray-600 text-xs">No</span>}
                </td>
                <td
                  className="px-6 py-4 text-gray-400 text-xs max-w-xs truncate"
                  title={row.phase2_action_reason ?? row.blast_radius_explanation ?? ''}
                >
                  {row.phase2_action_reason ?? row.blast_radius_explanation ?? '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
