interface Alert {
  severity: string;
  type: string;
  message: string;
  resource: string;
  createdAt: string | null;
}

const SEVERITY_BADGE: Record<string, string> = {
  Critical: 'bg-red-900/60 text-red-300 border border-red-800',
  High:     'bg-orange-900/60 text-orange-300 border border-orange-800',
  Warning:  'bg-yellow-900/60 text-yellow-300 border border-yellow-800',
};

const SEVERITY_DOT: Record<string, string> = {
  Critical: 'bg-red-500',
  High:     'bg-orange-500',
  Warning:  'bg-yellow-500',
};

function fmt(ts: string | null) {
  if (!ts) return '—';
  return new Date(ts).toLocaleString('en-US', {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

export default function AlertsPanel({ alerts, error }: { alerts: Alert[]; error?: string }) {
  if (error) {
    return (
      <div className="bg-red-950 border border-red-800 rounded-xl p-6 text-red-300 text-sm">
        Failed to load alerts: {error}
      </div>
    );
  }

  if (!alerts?.length) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-10 text-center">
        <p className="text-gray-400">No alerts</p>
        <p className="text-gray-600 text-xs mt-1">Alerts fire on pipeline failures, guardrail blocks, and Phase 3 parse errors</p>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      <div className="px-6 py-4 border-b border-gray-800 flex items-center justify-between">
        <h3 className="text-white font-semibold">Alerts</h3>
        <span className="text-gray-500 text-xs">{alerts.length} open</span>
      </div>
      <div className="divide-y divide-gray-800/60">
        {alerts.map((alert, i) => (
          <div key={i} className="px-6 py-4 hover:bg-gray-800/20 transition-colors flex items-start gap-4">
            <span className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${SEVERITY_DOT[alert.severity] ?? 'bg-gray-500'}`} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${SEVERITY_BADGE[alert.severity] ?? 'bg-gray-800 text-gray-400'}`}>
                  {alert.severity}
                </span>
                <span className="text-gray-500 text-xs">{alert.type}</span>
              </div>
              <p className="text-white text-sm">{alert.message}</p>
              <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
                <span className="font-mono">{alert.resource}</span>
                <span>{fmt(alert.createdAt)}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
