'use client';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell,
} from 'recharts';

interface WasteItem {
  waste_type: string;
  action: string;
  count: number;
  total_savings: number;
}

const TYPE_COLORS: Record<string, string> = {
  zombie: '#EF4444',
  idle: '#F97316',
  oversized: '#EAB308',
  tag_error: '#6B7280',
  none: '#374151',
};

export default function WasteBreakdownChart({ data }: { data: WasteItem[] }) {
  if (!data?.length) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 flex items-center justify-center h-64">
        <p className="text-gray-500 text-sm">No waste data yet</p>
      </div>
    );
  }

  const chartData = data.map(d => ({
    name: d.waste_type,
    Resources: d.count,
    savings: Number(d.total_savings),
  }));

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
      <h3 className="text-white font-semibold mb-4">EC2 Waste Breakdown</h3>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={chartData} margin={{ top: 4, right: 16, left: -10, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1F2937" />
          <XAxis dataKey="name" tick={{ fill: '#9CA3AF', fontSize: 12 }} />
          <YAxis tick={{ fill: '#9CA3AF', fontSize: 12 }} />
          <Tooltip
            contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: 8 }}
            labelStyle={{ color: '#F9FAFB', fontWeight: 600 }}
            itemStyle={{ color: '#9CA3AF' }}
            formatter={(v) => [v, 'Resources']}
          />
          <Bar dataKey="Resources" radius={[4, 4, 0, 0]}>
            {chartData.map((entry, i) => (
              <Cell key={i} fill={TYPE_COLORS[entry.name] ?? '#3B82F6'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
