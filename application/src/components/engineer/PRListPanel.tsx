interface PR {
  id: number;
  number: number;
  title: string;
  state: string;
  draft: boolean;
  html_url: string;
  head_ref: string;
  base_ref: string;
  created_at: string;
  updated_at: string;
  merged_at: string | null;
  user: string;
}

function StateBadge({ state, draft, merged_at }: { state: string; draft: boolean; merged_at: string | null }) {
  if (merged_at)  return <span className="px-2 py-0.5 rounded text-xs font-medium bg-purple-900/60 text-purple-300 border border-purple-800">merged</span>;
  if (draft)      return <span className="px-2 py-0.5 rounded text-xs font-medium bg-gray-800 text-gray-400">draft</span>;
  if (state === 'open')   return <span className="px-2 py-0.5 rounded text-xs font-medium bg-green-900/60 text-green-300 border border-green-800">open</span>;
  return <span className="px-2 py-0.5 rounded text-xs font-medium bg-gray-800 text-gray-400">{state}</span>;
}

export default function PRListPanel({ prs, error }: { prs: PR[]; error?: string }) {
  if (error) {
    return (
      <div className="bg-red-950 border border-red-800 rounded-xl p-6 text-red-300 text-sm">
        Failed to load PRs: {error}
      </div>
    );
  }

  if (!prs?.length) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-10 text-center">
        <p className="text-gray-400">No pull requests found</p>
        <p className="text-gray-600 text-xs mt-1">PRs are created when PHASE3_CREATE_PR=1</p>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      <div className="px-6 py-4 border-b border-gray-800">
        <h3 className="text-white font-semibold">Pull Requests — finops-infra</h3>
        <p className="text-gray-500 text-xs mt-0.5">{prs.length} PRs</p>
      </div>
      <div className="divide-y divide-gray-800/60">
        {prs.map(pr => (
          <div key={pr.id} className="px-6 py-4 hover:bg-gray-800/30 transition-colors">
            <div className="flex items-start gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1.5">
                  <StateBadge state={pr.state} draft={pr.draft} merged_at={pr.merged_at} />
                  <span className="text-gray-500 text-xs">#{pr.number}</span>
                </div>
                <a
                  href={pr.html_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-white text-sm font-medium hover:text-blue-400 transition-colors"
                >
                  {pr.title}
                </a>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1.5 text-xs text-gray-500">
                  <span className="font-mono">{pr.head_ref} → {pr.base_ref}</span>
                  <span>by {pr.user}</span>
                  <span>{new Date(pr.created_at).toLocaleDateString('en-US', {
                    month: 'short', day: 'numeric', year: 'numeric',
                  })}</span>
                  {pr.merged_at && (
                    <span className="text-purple-400">
                      merged {new Date(pr.merged_at).toLocaleDateString('en-US', {
                        month: 'short', day: 'numeric',
                      })}
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
