from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


class RunState:
    def __init__(self, state_path: Path, log_path: Path) -> None:
        self.state_path = state_path
        self.log_path = log_path
        self.state: dict[str, Any] = {
            "status": "running",
            "pid": os.getpid(),
            "run_id": None,
            "started_at": utc_now(),
            "completed_at": None,
            "steps": [],
            "error": None,
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text("", encoding="utf-8")
        self.write()

    def write(self) -> None:
        self.state_path.write_text(json.dumps(self.state, indent=2, default=str), encoding="utf-8")

    def log(self, message: str) -> None:
        line = f"{utc_now()} {message}"
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        print(line, flush=True)

    def start_step(self, name: str) -> dict[str, Any]:
        step = {
            "name": name,
            "status": "running",
            "started_at": utc_now(),
            "completed_at": None,
            "message": None,
        }
        self.state["steps"].append(step)
        self.log(f"[{name}] started")
        self.write()
        return step

    def finish_step(self, step: dict[str, Any], status: str, message: str | None = None) -> None:
        step["status"] = status
        step["message"] = message
        step["completed_at"] = utc_now()
        self.log(f"[{step['name']}] {status}{': ' + message if message else ''}")
        self.write()


def import_agent0_main():
    agent0_app = ROOT / "agent0" / "app"
    if str(agent0_app) not in sys.path:
        sys.path.insert(0, str(agent0_app))
    spec = importlib.util.spec_from_file_location("agent0_app_main", agent0_app / "main.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load agent0 app main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def run_deterministic_phase(state: RunState) -> int:
    from agent1.phase1.detection import run_phase1
    from agent1.phase1.loader import load_rules
    from agent1.phase1.s3_detection import run_s3_phase1
    from agent1.phase2 import run_phase2
    from shared.db import connect_database
    from shared.persistence import (
        save_phase1_outputs,
        save_phase2_outputs,
        start_optimization_run,
        update_optimization_run_status,
    )

    database_url = os.environ.get("DATABASE_URL") or os.environ.get("NEON_DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL or NEON_DATABASE_URL is required")
    os.environ.setdefault("DATABASE_URL", database_url)

    rules_path = os.environ.get("RULES_PATH", "rules.yaml")
    rules = load_rules(rules_path)
    conn = await connect_database(database_url)
    try:
      run_id = await start_optimization_run(
          conn,
          workspace_key=os.environ.get("WORKSPACE_KEY"),
          trigger_context={
              "trigger": "dashboard_analyze",
              "terraform_repo_url": os.environ.get("PHASE3_TERRAFORM_REPO_URL"),
              "terraform_ref": os.environ.get("PHASE3_TERRAFORM_REF"),
              "terraform_subdir": os.environ.get("PHASE3_TERRAFORM_SUBDIR"),
          },
      )
      state.state["run_id"] = run_id
      state.write()

      await update_optimization_run_status(conn, run_id, "running_phase1")
      ec2_results = await run_phase1(conn, rules)
      s3_results = await run_s3_phase1(conn, rules.s3)
      await save_phase1_outputs(conn, run_id, ec2_results, s3_results)
      state.log(f"[phase1] saved ec2={len(ec2_results)} s3={len(s3_results)}")

      await update_optimization_run_status(conn, run_id, "running_phase2")
      phase2_results = await run_phase2(conn, ec2_results, rules.phase2)
      await save_phase2_outputs(conn, run_id, phase2_results)
      await update_optimization_run_status(conn, run_id, "waiting_phase3")
      state.log(f"[phase2] saved ec2={len(phase2_results)}")
      return run_id
    finally:
        await conn.close()


async def run_llm_phase(state: RunState, run_id: int) -> None:
    from agent2.phase3.llm_phase3 import run_phase3_llm
    from shared.db import connect_database
    from shared.persistence import (
        complete_optimization_run,
        load_phase1_ec2_outputs,
        load_phase1_s3_outputs,
        load_phase2_ec2_outputs,
        save_phase3_outputs,
        update_optimization_run_status,
    )

    database_url = os.environ.get("DATABASE_URL") or os.environ.get("NEON_DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL or NEON_DATABASE_URL is required")

    conn = await connect_database(database_url)
    ec2_phase1 = []
    s3_phase1 = []
    ec2_phase2 = []
    try:
        await update_optimization_run_status(conn, run_id, "running_phase3")
        ec2_phase1 = await load_phase1_ec2_outputs(conn, run_id)
        s3_phase1 = await load_phase1_s3_outputs(conn, run_id)
        ec2_phase2 = await load_phase2_ec2_outputs(conn, run_id)
        state.log(
            f"[phase3] loaded ec2_phase1={len(ec2_phase1)} "
            f"s3_phase1={len(s3_phase1)} ec2_phase2={len(ec2_phase2)}"
        )
    finally:
        await conn.close()

    phase3_output = await asyncio.to_thread(
        run_phase3_llm,
        ec2_phase1,
        ec2_phase2,
        s3_phase1,
        model_key=os.environ.get("PHASE3_MODEL") or None,
        terraform_source={
            "repo_url": os.environ.get("PHASE3_TERRAFORM_REPO_URL"),
            "ref": os.environ.get("PHASE3_TERRAFORM_REF"),
            "subdir": os.environ.get("PHASE3_TERRAFORM_SUBDIR"),
        },
    )

    conn = await connect_database(database_url)
    try:
        if phase3_output.get("error"):
            raise RuntimeError(str(phase3_output["error"]))

        parse_errors = [
            str(run.get("llm", {}).get("parse_error"))
            for run in (phase3_output.get("runs") or [])
            if isinstance(run, dict) and run.get("llm", {}).get("parse_error")
        ]
        if parse_errors:
            raise RuntimeError("; ".join(sorted(set(parse_errors))))

        await save_phase3_outputs(
            conn,
            run_id,
            phase3_output,
            phase2_results=ec2_phase2,
            s3_results=s3_phase1,
        )
        await complete_optimization_run(conn, run_id, status="completed")

        patch_plan = phase3_output.get("patch_plan") or {}
        modified_files = patch_plan.get("modified_files") or []
        state.log(f"[phase3] saved modified_files={len(modified_files)}")
    except Exception:
        try:
            await update_optimization_run_status(
                conn,
                run_id,
                "phase3_failed",
                error_message="Dashboard analysis Phase 3 failed",
            )
        except Exception as status_exc:
            state.log(f"[phase3] could not mark failure status: {status_exc}")
        raise
    finally:
        await conn.close()


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--log", required=True)
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    if os.environ.get("NEON_DATABASE_URL") and not os.environ.get("DATABASE_URL"):
        os.environ["DATABASE_URL"] = os.environ["NEON_DATABASE_URL"]
    os.environ.setdefault("PHASE3_CREATE_PR", "0")
    os.environ.setdefault("PHASE3_EC2_LLM_VALIDATION", "1")
    os.environ.setdefault("PHASE3_TERRAFORM_REPO_URL", "https://github.com/Nour-Ben-Hadid/finops-infra.git")
    os.environ.setdefault("PHASE3_TERRAFORM_REF", "main")
    os.environ.setdefault("PHASE3_TERRAFORM_SUBDIR", "")

    state = RunState(Path(args.state), Path(args.log))
    try:
        step = state.start_step("ingestion")
        try:
            agent0_main = import_agent0_main()
            await asyncio.to_thread(agent0_main.run_full_pipeline)
            state.finish_step(step, "completed", "Agent0 ingestion finished")
        except Exception as exc:
            state.finish_step(step, "warning", f"Ingestion could not complete: {exc}")
            state.log(traceback.format_exc())

        step = state.start_step("phase1_phase2")
        run_id = await run_deterministic_phase(state)
        state.finish_step(step, "completed", f"Created optimization run {run_id}")

        step = state.start_step("phase3_preview")
        try:
            await run_llm_phase(state, run_id)
            state.finish_step(step, "completed", f"Saved Phase 3 outputs for run {run_id}")
        except Exception as exc:
            state.finish_step(step, "failed", str(exc))
            raise

        state.state["status"] = "completed"
        state.state["completed_at"] = utc_now()
        state.write()
        state.log("[analysis] completed")
        return 0
    except Exception as exc:
        state.state["status"] = "failed"
        state.state["error"] = str(exc)
        state.state["completed_at"] = utc_now()
        state.write()
        state.log("[analysis] failed: " + str(exc))
        state.log(traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
