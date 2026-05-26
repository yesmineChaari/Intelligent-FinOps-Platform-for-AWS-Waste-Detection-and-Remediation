'use client';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer,
} from 'recharts';

interface TrendPoint {
  label: string;
  savings: number;
}

export default function SavingsTrendChart({ data }: { data: TrendPoint[] }) {
  if (!data?.length) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 flex items-center justify-center h-64">
        <p className="text-gray-500 text-sm">Not enough runs for a trend yet</p>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
      <h3 className="text-white font-semibold mb-1">Savings Trend</h3>
      <p className="text-gray-500 text-xs mb-4">Monthly savings potential across last {data.length} completed runs</p>
      <ResponsiveContainer width="100%" height={200}>
        <AreaChart data={data} margin={{ top: 4, right: 16, left: -10, bottom: 4 }}>
          <defs>
            <linearGradient id="savingsGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#22C55E" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#22C55E" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1F2937" />
          <XAxis dataKey="label" tick={{ fill: '#9CA3AF', fontSize: 11 }} />
          <YAxis
            tick={{ fill: '#9CA3AF', fontSize: 11 }}
            tickFormatter={(v) => `$${v}`}
          />
          <Tooltip
            contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: 8 }}
            labelStyle={{ color: '#F9FAFB', fontWeight: 600 }}
            formatter={(v) => [`$${Number(v).toFixed(0)}/mo`, 'Savings']}
          />
          <Area
            type="monotone"
            dataKey="savings"
            stroke="#22C55E"
            strokeWidth={2}
            fill="url(#savingsGradient)"
            dot={{ fill: '#22C55E', r: 3 }}
            activeDot={{ r: 5 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
