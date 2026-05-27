import { NextResponse } from 'next/server';

function cleanEnv(value: string | undefined) {
  return (value ?? '').trim().replace(/^['"]|['"]$/g, '');
}

function parseGitHubRepo(value: string) {
  const input = value.trim();
  const short = input.match(/^([^/\s]+)\/([^/\s]+)$/);
  if (short) return `${short[1]}/${short[2].replace(/\.git$/, '')}`;

  const ssh = input.match(/^git@github\.com:([^/\s]+)\/([^/\s]+?)(?:\.git)?$/);
  if (ssh) return `${ssh[1]}/${ssh[2]}`;

  try {
    const url = new URL(input);
    if (url.hostname.toLowerCase() !== 'github.com') return null;
    const parts = url.pathname.replace(/^\/|\/$/g, '').replace(/\.git$/, '').split('/');
    if (parts.length !== 2 || !parts[0] || !parts[1]) return null;
    return `${parts[0]}/${parts[1]}`;
  } catch {
    return null;
  }
}

export async function GET() {
  const configuredRepo =
    cleanEnv(process.env.GITHUB_REPO)
    || cleanEnv(process.env.PHASE3_TERRAFORM_REPO_URL);
  const repo = configuredRepo ? parseGitHubRepo(configuredRepo) : null;
  const token = cleanEnv(process.env.GITHUB_TOKEN) || cleanEnv(process.env.GH_TOKEN) || cleanEnv(process.env.GITHUB_PAT);

  if (!repo) {
    return NextResponse.json(
      { error: 'Set GITHUB_REPO or PHASE3_TERRAFORM_REPO_URL to load pull requests.' },
      { status: 500 },
    );
  }

  try {
    const headers: Record<string, string> = {
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    };
    if (token) headers.Authorization = `Bearer ${token}`;

    const res = await fetch(
      `https://api.github.com/repos/${repo}/pulls?state=all&per_page=50&sort=created&direction=desc`,
      {
        headers,
        cache: 'no-store',
      },
    );

    if (!res.ok) {
      const text = await res.text();
      return NextResponse.json({ error: text }, { status: res.status });
    }

    const prs: any[] = await res.json();
    return NextResponse.json(
      prs.map(pr => ({
        id: pr.id,
        number: pr.number,
        title: pr.title,
        state: pr.state,
        draft: pr.draft,
        html_url: pr.html_url,
        head_ref: pr.head?.ref,
        base_ref: pr.base?.ref,
        created_at: pr.created_at,
        updated_at: pr.updated_at,
        merged_at: pr.merged_at,
        user: pr.user?.login,
      })),
    );
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
