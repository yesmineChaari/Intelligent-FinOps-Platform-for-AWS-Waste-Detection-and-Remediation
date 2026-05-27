import { spawn } from 'child_process';
import { existsSync, mkdirSync, readFileSync } from 'fs';
import path from 'path';
import { NextResponse } from 'next/server';

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

function cleanEnvValue(value: string | undefined) {
  return (value ?? '').trim().replace(/^['"]|['"]$/g, '');
}

export async function GET() {
  return NextResponse.json(currentStatus());
}

export async function POST() {
  mkdirSync(stateDir, { recursive: true });

  const existing = currentStatus();
  if (existing.running) {
    return NextResponse.json(existing);
  }

  const scriptPath = path.join(repoRoot, 'scripts', 'run_dashboard_analysis.py');
  const databaseUrl = cleanEnvValue(process.env.DATABASE_URL) || cleanEnvValue(process.env.NEON_DATABASE_URL);
  const child = spawn(
    'python',
    [scriptPath, '--state', statePath, '--log', logPath],
    {
      cwd: repoRoot,
      detached: true,
      stdio: 'ignore',
      env: {
        ...process.env,
        DATABASE_URL: databaseUrl,
        NEON_DATABASE_URL: databaseUrl,
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
