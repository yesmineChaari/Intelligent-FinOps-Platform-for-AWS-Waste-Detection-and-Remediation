import { spawn } from 'child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'fs';
import path from 'path';
import { NextResponse } from 'next/server';
import { MOCK_RUN_ID, resetMockPreview } from '@/lib/mock-run';

export const runtime = 'nodejs';

const repoRoot = path.resolve(process.cwd(), '..');
const stateDir = path.join(process.cwd(), '.analysis');
const statePath = path.join(stateDir, 'latest.json');
const logPath = path.join(stateDir, 'latest.log');

function readJson(filePath: string) {
  if (!existsSync(filePath)) return null;
  try {
    return JSON.parse(readFileSync(filePath, 'utf8'));
  } catch {
    return null;
  }
}

function readLogTail(filePath: string, maxChars = 16000) {
  if (!existsSync(filePath)) return '';
  const text = readFileSync(filePath, 'utf8');
  return text.length > maxChars ? text.slice(text.length - maxChars) : text;
}

function isAlive(pid: number | null | undefined) {
  if (!pid) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function currentStatus() {
  const state = readJson(statePath);
  const log = readLogTail(logPath);
  const running = state?.status === 'running' && isAlive(Number(state?.pid));
  return { state, log, running };
}

function writeReplayState(runId: number | string) {
  mkdirSync(stateDir, { recursive: true });
  const now = new Date().toISOString();
  const state = {
    status: 'completed',
    pid: null,
    run_id: Number(runId),
    started_at: now,
    completed_at: now,
    steps: [
      {
        name: 'replay_fixture',
        status: 'completed',
        started_at: now,
        completed_at: now,
        message: `Replayed saved successful run ${runId}; no backend pipeline or LLM API was called.`,
      },
    ],
    error: null,
    replay: true,
  };
  const log = [
    `${now} [replay_fixture] started`,
    `${now} [replay_fixture] completed: using saved successful run ${runId}`,
    `${now} [analysis] completed without API calls`,
    '',
  ].join('\n');
  writeFileSync(statePath, JSON.stringify(state, null, 2), 'utf8');
  writeFileSync(logPath, log, 'utf8');
  return { state, log, running: false };
}

export async function GET() {
  return NextResponse.json(currentStatus());
}

export async function POST(req: Request) {
  mkdirSync(stateDir, { recursive: true });

  const existing = currentStatus();
  if (existing.running) {
    return NextResponse.json(existing);
  }

  let mode = '';
  try {
    const body = await req.json();
    mode = String(body?.mode ?? '');
  } catch {
    mode = '';
  }

  if (mode === 'replay') {
    resetMockPreview();
    return NextResponse.json(writeReplayState(MOCK_RUN_ID));
  }

  const scriptPath = path.join(repoRoot, 'scripts', 'run_dashboard_analysis.py');
  const child = spawn(
    'python',
    [scriptPath, '--state', statePath, '--log', logPath],
    {
      cwd: repoRoot,
      detached: true,
      stdio: 'ignore',
      env: {
        ...process.env,
        DATABASE_URL: process.env.DATABASE_URL || process.env.NEON_DATABASE_URL || '',
        PHASE3_CREATE_PR: '0',
      },
      windowsHide: true,
    },
  );
  child.unref();

  return NextResponse.json({
    state: {
      status: 'starting',
      pid: child.pid,
      run_id: null,
      started_at: new Date().toISOString(),
      completed_at: null,
      steps: [],
      error: null,
    },
    log: '',
    running: true,
  });
}
