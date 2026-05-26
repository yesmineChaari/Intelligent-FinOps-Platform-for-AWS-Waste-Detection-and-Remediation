interface MetricCardProps {
  label: string;
  value: string;
  sublabel?: string;
  color?: 'green' | 'blue' | 'purple' | 'yellow';
  icon?: string;
}

const COLOR_MAP = {
  green: 'text-green-400',
  blue: 'text-blue-400',
  purple: 'text-purple-400',
  yellow: 'text-yellow-400',
};

export default function MetricCard({ label, value, sublabel, color = 'green', icon }: MetricCardProps) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-gray-400 text-sm mb-1">{label}</p>
          <p className={`text-3xl font-bold ${COLOR_MAP[color]}`}>{value}</p>
          {sublabel && <p className="text-gray-500 text-xs mt-1">{sublabel}</p>}
        </div>
        {icon && <span className="text-2xl opacity-80">{icon}</span>}
      </div>
    </div>
  );
}
