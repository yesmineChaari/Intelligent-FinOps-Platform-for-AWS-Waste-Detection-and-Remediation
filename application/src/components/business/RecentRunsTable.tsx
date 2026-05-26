interface Run {
  id: number;
  workspace_key: string | null;
  status: string;
  started_at: string;
  completed_at: string | null;
  phase3_model_key: string | null;
  ec2_count: number;
  s3_count: number;
  ec2_savings: number;
  s3_savings: number;
}

const STATUS_BADGE: Record<string, string> = {
  completed: 'bg-green-900/60 text-green-300 border border-green-800',
  running:   'bg-blue-900/60 text-blue-300 border border-blue-800',
  failed:    'bg-red-900/60 text-red-300 border border-red-800',
};

function fmt(date: string | null) {
  if (!date) return '—';
  return new Date(date).toLocaleString('en-US', {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

export default function RecentRunsTable({ runs }: { runs: Run[] }) {
  if (!runs?.length) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-8 text-center text-gray-500 text-sm">
        No optimization runs yet — start the pfa pipeline to generate data.
      </div>
    );
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      <div className="px-6 py-4 border-b border-gray-800">
        <h3 className="text-white font-semibold">Recent Optimization Runs</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800">
              <th className="text-left px-6 py-3 text-gray-400 font-medium">Run</th>
              <th className="text-left px-6 py-3 text-gray-400 font-medium">Status</th>
              <th className="text-left px-6 py-3 text-gray-400 font-medium">Started</th>
              <th className="text-left px-6 py-3 text-gray-400 font-medium">Model</th>
              <th className="text-right px-6 py-3 text-gray-400 font-medium">EC2</th>
              <th className="text-right px-6 py-3 text-gray-400 font-medium">S3</th>
              <th className="text-right px-6 py-3 text-gray-400 font-medium">Savings / mo</th>
            </tr>
          </thead>
          <tbody>
            {runs.map(run => (
              <tr key={run.id} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                <td className="px-6 py-4">
                  <span className="text-white font-mono text-xs">#{run.id}</span>
                  {run.workspace_key && (
                    <span className="ml-2 text-gray-500 text-xs">{run.workspace_key}</span>
                  )}
                </td>
                <td className="px-6 py-4">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_BADGE[run.status] ?? 'bg-gray-800 text-gray-400'}`}>
                    {run.status}
                  </span>
                </td>
                <td className="px-6 py-4 text-gray-400">{fmt(run.started_at)}</td>
                <td className="px-6 py-4 text-gray-500 text-xs">{run.phase3_model_key ?? '—'}</td>
                <td className="px-6 py-4 text-right text-white">{run.ec2_count}</td>
                <td className="px-6 py-4 text-right text-white">{run.s3_count}</td>
                <td className="px-6 py-4 text-right font-semibold text-green-400">
                  ${(Number(run.ec2_savings) + Number(run.s3_savings)).toFixed(0)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
