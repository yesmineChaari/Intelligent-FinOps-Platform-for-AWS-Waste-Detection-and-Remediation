'use client';
import { useState, useEffect } from 'react';
import MetricCard from '@/components/business/MetricCard';
import WasteBreakdownChart from '@/components/business/WasteBreakdownChart';
import RecentRunsTable from '@/components/business/RecentRunsTable';

interface Summary {
  ec2_savings: number;
  s3_savings: number;
  completed_runs: number;
  total_runs: number;
  ec2_flagged: number;
  s3_flagged: number;
}

interface WasteItem {
  waste_type: string;
  action: string;
  count: number;
  total_savings: number;
}

function Spinner() {
  return (
    <div className="flex items-center justify-center h-64">
      <div className="animate-spin w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full" />
    </div>
  );
}

export default function BusinessDashboard() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [wasteBreakdown, setWasteBreakdown] = useState<WasteItem[]>([]);
  const [runs, setRuns] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetch('/api/costs').then(r => r.json()),
      fetch('/api/runs').then(r => r.json()),
    ])
      .then(([costsData, runsData]) => {
        setSummary(costsData.summary ?? null);
        setWasteBreakdown(costsData.wasteBreakdown ?? []);
        setRuns(Array.isArray(runsData) ? runsData : []);
      })
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Spinner />;

  if (error) {
    return (
      <div className="bg-red-950 border border-red-800 rounded-xl p-6 text-red-300 text-sm">
        Failed to load dashboard: {error}
      </div>
    );
  }

  const ec2Savings = Number(summary?.ec2_savings ?? 0);
  const s3Savings  = Number(summary?.s3_savings ?? 0);
  const total      = ec2Savings + s3Savings;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Cost Overview</h1>
        <p className="text-gray-400 text-sm mt-1">
          AWS infrastructure waste detection &amp; savings potential
        </p>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Total Savings Potential"
          value={`$${total.toFixed(0)}/mo`}
          sublabel="EC2 + S3 combined"
          color="green"
          icon="💰"
        />
        <MetricCard
          label="EC2 Savings"
          value={`$${ec2Savings.toFixed(0)}/mo`}
          sublabel={`${summary?.ec2_flagged ?? 0} instances flagged`}
          color="blue"
          icon="⚡"
        />
        <MetricCard
          label="S3 Savings"
          value={`$${s3Savings.toFixed(0)}/mo`}
          sublabel={`${summary?.s3_flagged ?? 0} buckets flagged`}
          color="purple"
          icon="🪣"
        />
        <MetricCard
          label="Optimization Runs"
          value={String(summary?.completed_runs ?? 0)}
          sublabel={`${summary?.total_runs ?? 0} total (incl. running)`}
          color="yellow"
          icon="🔄"
        />
      </div>

      {/* Chart + savings summary */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <div className="lg:col-span-3">
          <WasteBreakdownChart data={wasteBreakdown} />
        </div>
        <div className="lg:col-span-2">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 h-full">
            <h3 className="text-white font-semibold mb-4">Savings by Category</h3>
            <div className="space-y-3">
              {wasteBreakdown.map(item => (
                <div
                  key={`${item.waste_type}-${item.action}`}
                  className="flex items-center justify-between"
                >
                  <div className="flex items-center gap-2">
                    <span
                      className={`w-2 h-2 rounded-full ${
                        item.waste_type === 'zombie'   ? 'bg-red-500' :
                        item.waste_type === 'idle'     ? 'bg-orange-500' :
                        item.waste_type === 'oversized'? 'bg-yellow-500' :
                        'bg-gray-500'
                      }`}
                    />
                    <span className="text-gray-300 text-sm capitalize">{item.waste_type}</span>
                    <span className="text-gray-600 text-xs">×{item.count}</span>
                  </div>
                  <span className="text-green-400 font-medium text-sm">
                    ${Number(item.total_savings).toFixed(0)}/mo
                  </span>
                </div>
              ))}

              {wasteBreakdown.length === 0 && (
                <p className="text-gray-500 text-sm">No waste detected yet</p>
              )}

              {wasteBreakdown.length > 0 && (
                <div className="pt-3 border-t border-gray-800 flex items-center justify-between">
                  <span className="text-white font-semibold">Total</span>
                  <span className="text-green-400 font-bold text-xl">${total.toFixed(0)}/mo</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      <RecentRunsTable runs={runs} />
    </div>
  );
}
