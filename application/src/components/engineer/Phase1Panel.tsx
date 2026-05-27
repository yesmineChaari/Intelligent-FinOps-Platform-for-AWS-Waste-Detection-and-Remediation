import ActionBadge from './ActionBadge';

interface EC2Row {
  id: number;
  resource_name: string | null;
  role: string | null;
  action: string;
  waste_type: string;
  current_instance_type: string | null;
  recommended_type: string | null;
  current_cost_per_hour: number | null;
  recommended_cost_per_hour: number | null;
  waste_per_month: number | null;
  detection_reason: string | null;
  metrics: Record<string, unknown>;
  region: string | null;
  avg_cpu: number | null;
  avg_ram: number | null;
  telemetry_p95_cpu: number | null;
}

interface S3Row {
  id: number;
  bucket_name: string;
  action: string;
  waste_type: string;
  detection_reason: string | null;
  recommended_action: string | null;
  metrics: Record<string, unknown>;
  region: string | null;
  inv_object_count: number | null;
  inv_size_bytes: number | null;
}

function fmtPct(v: number | null) {
  if (v == null) return '—';
  return `${Number(v).toFixed(1)}%`;
}

function fmtBytes(bytes: number | null) {
  if (bytes == null) return '—';
  if (bytes >= 1e12) return `${(bytes / 1e12).toFixed(1)} TB`;
  if (bytes >= 1e9)  return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6)  return `${(bytes / 1e6).toFixed(1)} MB`;
  return `${bytes} B`;
}

function SectionHeader({ title, count }: { title: string; count: number }) {
  return (
    <div className="px-6 py-4 border-b border-gray-800 flex items-center justify-between">
      <h3 className="text-white font-semibold">{title}</h3>
      <span className="text-gray-500 text-xs">{count} {count === 1 ? 'item' : 'items'}</span>
    </div>
  );
}

export default function Phase1Panel({ ec2, s3 }: { ec2: EC2Row[]; s3: S3Row[] }) {
  return (
    <div className="space-y-6">
      {/* EC2 */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <SectionHeader title="EC2 Findings" count={ec2.length} />
        {ec2.length === 0 ? (
          <div className="px-6 py-8 text-center text-gray-500 text-sm">No EC2 findings for this run</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800">
                  <th className="text-left px-6 py-3 text-gray-400 font-medium">Instance</th>
                  <th className="text-left px-6 py-3 text-gray-400 font-medium">Region</th>
                  <th className="text-left px-6 py-3 text-gray-400 font-medium">Role</th>
                  <th className="text-left px-6 py-3 text-gray-400 font-medium">Action</th>
                  <th className="text-left px-6 py-3 text-gray-400 font-medium">Type change</th>
                  <th className="text-right px-6 py-3 text-gray-400 font-medium">CPU avg</th>
                  <th className="text-right px-6 py-3 text-gray-400 font-medium">CPU p95</th>
                  <th className="text-right px-6 py-3 text-gray-400 font-medium">RAM avg</th>
                  <th className="text-right px-6 py-3 text-gray-400 font-medium">Waste / mo</th>
                  <th className="text-left px-6 py-3 text-gray-400 font-medium">Reason</th>
                </tr>
              </thead>
              <tbody>
                {ec2.map(row => (
                  <tr key={row.id} className="border-b border-gray-800/50 hover:bg-gray-800/20 transition-colors">
                    <td className="px-6 py-4 font-mono text-xs text-white">{row.resource_name ?? '—'}</td>
                    <td className="px-6 py-4 text-gray-400 text-xs">{row.region ?? '—'}</td>
                    <td className="px-6 py-4 text-gray-400 text-xs">{row.role ?? '—'}</td>
                    <td className="px-6 py-4"><ActionBadge action={row.action} /></td>
                    <td className="px-6 py-4 text-gray-300 text-xs">
                      {row.current_instance_type ? (
                        <>
                          {row.current_instance_type}
                          {row.recommended_type && row.recommended_type !== row.current_instance_type && (
                            <> → <span className="text-green-400">{row.recommended_type}</span></>
                          )}
                        </>
                      ) : '—'}
                    </td>
                    <td className="px-6 py-4 text-right text-xs text-gray-300">{fmtPct(row.avg_cpu)}</td>
                    <td className="px-6 py-4 text-right text-xs text-gray-300">{fmtPct(row.telemetry_p95_cpu)}</td>
                    <td className="px-6 py-4 text-right text-xs text-gray-300">{fmtPct(row.avg_ram)}</td>
                    <td className="px-6 py-4 text-right font-medium text-yellow-400">
                      {row.waste_per_month ? `$${Number(row.waste_per_month).toFixed(0)}` : '—'}
                    </td>
                    <td className="px-6 py-4 text-gray-400 text-xs max-w-xs truncate" title={row.detection_reason ?? ''}>
                      {row.detection_reason ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* S3 */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <SectionHeader title="S3 Findings" count={s3.length} />
        {s3.length === 0 ? (
          <div className="px-6 py-8 text-center text-gray-500 text-sm">No S3 findings for this run</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800">
                  <th className="text-left px-6 py-3 text-gray-400 font-medium">Bucket</th>
                  <th className="text-left px-6 py-3 text-gray-400 font-medium">Region</th>
                  <th className="text-left px-6 py-3 text-gray-400 font-medium">Waste type</th>
                  <th className="text-left px-6 py-3 text-gray-400 font-medium">Action</th>
                  <th className="text-right px-6 py-3 text-gray-400 font-medium">Objects</th>
                  <th className="text-right px-6 py-3 text-gray-400 font-medium">Size</th>
                  <th className="text-right px-6 py-3 text-gray-400 font-medium">Est. savings / mo</th>
                  <th className="text-left px-6 py-3 text-gray-400 font-medium">Reason</th>
                </tr>
              </thead>
              <tbody>
                {s3.map(row => (
                  <tr key={row.id} className="border-b border-gray-800/50 hover:bg-gray-800/20 transition-colors">
                    <td className="px-6 py-4 font-mono text-xs text-white">{row.bucket_name}</td>
                    <td className="px-6 py-4 text-gray-400 text-xs">{row.region ?? '—'}</td>
                    <td className="px-6 py-4 text-gray-400 text-xs">{row.waste_type}</td>
                    <td className="px-6 py-4"><ActionBadge action={row.action} /></td>
                    <td className="px-6 py-4 text-right text-xs text-gray-300">
                      {row.inv_object_count != null ? row.inv_object_count.toLocaleString() : '—'}
                    </td>
                    <td className="px-6 py-4 text-right text-xs text-gray-300">{fmtBytes(row.inv_size_bytes)}</td>
                    <td className="px-6 py-4 text-right font-medium text-yellow-400">
                      {row.metrics?.estimated_monthly_savings
                        ? `$${Number(row.metrics.estimated_monthly_savings).toFixed(2)}`
                        : '—'}
                    </td>
                    <td className="px-6 py-4 text-gray-400 text-xs max-w-xs truncate" title={row.detection_reason ?? ''}>
                      {row.detection_reason ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
