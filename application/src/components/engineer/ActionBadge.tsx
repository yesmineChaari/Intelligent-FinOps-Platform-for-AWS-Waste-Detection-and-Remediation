const ACTION_BADGE: Record<string, string> = {
  TERMINATE: 'bg-red-900/60 text-red-300 border border-red-800',
  STOP: 'bg-orange-900/60 text-orange-300 border border-orange-800',
  DOWNSIZE: 'bg-yellow-900/60 text-yellow-300 border border-yellow-800',
  REVIEW: 'bg-blue-900/60 text-blue-300 border border-blue-800',
  SKIP: 'bg-gray-800 text-gray-500 border border-gray-700',
  CLEAN: 'bg-purple-900/60 text-purple-300 border border-purple-800',
  RECOMMEND_LIFECYCLE: 'bg-teal-900/60 text-teal-300 border border-teal-800',
};

export function actionLabel(action: string | null | undefined) {
  return (action || 'UNKNOWN').toUpperCase();
}

export default function ActionBadge({
  action,
  className = '',
}: {
  action: string | null | undefined;
  className?: string;
}) {
  const label = actionLabel(action);
  const tone = ACTION_BADGE[label] ?? 'bg-gray-800 text-gray-400 border border-gray-700';

  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${tone} ${className}`}>
      {label}
    </span>
  );
}
