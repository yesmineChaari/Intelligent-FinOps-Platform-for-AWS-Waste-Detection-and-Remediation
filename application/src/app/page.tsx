'use client';
import { useState, useEffect } from 'react';
import MetricCard from '@/components/business/MetricCard';
import WasteBreakdownChart from '@/components/business/WasteBreakdownChart';
import SavingsTrendChart from '@/components/business/SavingsTrendChart';
import RecentRunsTable from '@/components/business/RecentRunsTable';

interface Summary {
  ec2_savings: number;
  s3_savings: number;
  completed_runs: number;
  total_runs: number;
  ec2_flagged: number;
  s3_flagged: number;
  blocked_count: number;
}

function Spinner() {
  return (
    <div className="flex items-center justify-center h-64">
      <div className="animate-spin w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full" />
    </div>
  );
}

export default function BusinessDashboard() {
  const [summary,        setSummary]        = useState<Summary | null>(null);
  const [wasteBreakdown, setWasteBreakdown] = useState<any[]>([]);
  const [trend,          setTrend]          = useState<any[]>([]);
  const [runs,           setRuns]           = useState<any[]>([]);
  const [loading,        setLoading]        = useState(true);
  const [error,          setError]          = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetch('/api/costs').then(r => r.json()),
      fetch('/api/runs').then(r => r.json()),
    ])
      .then(([costsData, runsData]) => {
        setSummary(costsData.summary ?? null);
        setWasteBreakdown(costsData.wasteBreakdown ?? []);
        setTrend(costsData.trend ?? []);
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
        <p className="text-gray-400 text-sm mt-1">AWS infrastructure waste detection &amp; savings potential</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard label="Total Savings Potential" value={`$${total.toFixed(0)}/mo`}
          sublabel="EC2 + S3 combined" color="green" />
        <MetricCard label="EC2 Savings" value={`$${ec2Savings.toFixed(0)}/mo`}
          sublabel={`${summary?.ec2_flagged ?? 0} instances flagged`} color="blue" />
        <MetricCard label="S3 Savings" value={`$${s3Savings.toFixed(0)}/mo`}
          sublabel={`${summary?.s3_flagged ?? 0} buckets flagged`} color="purple" />
        <MetricCard label="Blocked by Guardrails" value={String(summary?.blocked_count ?? 0)}
          sublabel="Requires manual review" color="yellow" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <SavingsTrendChart data={trend} />
        <WasteBreakdownChart data={wasteBreakdown} />
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
        <h3 className="text-white font-semibold mb-4">Savings by Category</h3>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
          {wasteBreakdown.filter(item => Number(item.total_savings) > 0).map(item => (
            <div key={`${item.waste_type}-${item.action}`}
              className="bg-gray-800/50 rounded-lg p-4 text-center">
              <p className="text-green-400 font-bold text-lg">${Number(item.total_savings).toFixed(0)}</p>
              <p className="text-gray-300 text-xs mt-1 capitalize">{item.waste_type}</p>
              <p className="text-gray-600 text-xs">{item.count} instance{item.count !== 1 ? 's' : ''}</p>
            </div>
          ))}
          {wasteBreakdown.filter(item => Number(item.total_savings) > 0).length === 0 && (
            <p className="text-gray-500 text-sm col-span-full">No savings detected yet</p>
          )}
        </div>
        {total > 0 && (
          <div className="mt-4 pt-4 border-t border-gray-800 flex justify-between items-center">
            <span className="text-gray-400">Total potential</span>
            <span className="text-green-400 font-bold text-xl">${total.toFixed(0)}/mo</span>
          </div>
        )}
      </div>

      <RecentRunsTable runs={runs} />
    </div>
  );
}
