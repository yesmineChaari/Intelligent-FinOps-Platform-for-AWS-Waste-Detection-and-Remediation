"""
End-to-end test for the terraform retrieval → LLM → patch → PR flow.

Usage:
    export GITHUB_TOKEN=ghp_...
    export PHASE3_TERRAFORM_REPO_URL=https://github.com/yesmineChaari/finops-infra
    export PHASE3_MODEL=qwen3-coder-32b          # or llama3.3-70b / gemini-2.5-flash
    export GROQ_API_KEY=...                       # or GOOGLE_API_KEY / MISTRAL_API_KEY
    export PHASE3_CREATE_PR=1                     # set to 0 to skip PR creation
    export PHASE3_PR_DRAFT=1                      # open as draft PR (safe)
    export PHASE3_RUN_TERRAFORM_VALIDATE=0        # skip terraform validate locally

    python test_pr_flow.py
"""

import json
import os
import sys
from pathlib import Path

# ── make phase3 importable ────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from phase1.models import Phase1Result, WasteAction, WasteType
from phase2.models import Phase2Result
from phase3.llm_phase3 import run_phase3_llm


# ── Mock Phase 1 EC2 results ──────────────────────────────────────────────────
# i-001: dependant_primary, oversized → DOWNSIZE c5.xlarge → c5.large
# i-006: steady zombie, isolated      → TERMINATE

MOCK_EC2_PHASE1 = [
    Phase1Result(
        resource_id=1,
        resource_name="i-001",
        role="dependant_primary",
        action=WasteAction.DOWNSIZE,
        waste_type=WasteType.OVERSIZED,
        detection_window_days=30,
        p95_cpu=3.2,
        p99_cpu=5.1,
        max_cpu=9.8,
        p95_ram=18.4,
        cv=0.18,
        current_instance_type="c5.xlarge",
        recommended_type="c5.large",
        current_cost_per_hour=0.192,
        recommended_cost_per_hour=0.096,
        waste_per_month=69.12,
        detection_reason="Dependant primary idle: P95 CPU 3.2% and P95 RAM 18.4% below thresholds.",
    ),
    Phase1Result(
        resource_id=6,
        resource_name="i-006",
        role="steady",
        action=WasteAction.TERMINATE,
        waste_type=WasteType.ZOMBIE,
        detection_window_days=30,
        stopped_days=45,
        current_instance_type="m5.large",
        current_cost_per_hour=0.096,
        waste_per_month=69.12,
        detection_reason="Zombie: instance is stopped and last EC2 metric is 45 days old (threshold=30).",
    ),
]

# ── Mock Phase 2 EC2 results ──────────────────────────────────────────────────
# i-001: blast_radius=4, action kept as DOWNSIZE (below terminate_max_score)
# i-006: blast_radius=0, isolated → TERMINATE confirmed

MOCK_EC2_PHASE2 = [
    Phase2Result(
        resource_id=1,
        instance_name="i-001",
        role="dependant_primary",
        waste_type=WasteType.OVERSIZED,
        phase1_action=WasteAction.DOWNSIZE,
        action=WasteAction.DOWNSIZE,
        detection_reason="Dependant primary idle: P95 CPU 3.2% and P95 RAM 18.4% below thresholds.",
        phase2_action_changed=False,
        blast_radius=4,
        relationship_count=3,
        blast_radius_explanation="Writes to r-001 (DynamoDB) and r-002 (S3). Score=4, below downsize_max_score=8.",
        instance_type="c5.xlarge",
        recommended_type="c5.large",
        current_cost_per_hour=0.192,
        recommended_cost_per_hour=0.096,
        waste_per_month=69.12,
    ),
    Phase2Result(
        resource_id=6,
        instance_name="i-006",
        role="steady",
        waste_type=WasteType.ZOMBIE,
        phase1_action=WasteAction.TERMINATE,
        action=WasteAction.TERMINATE,
        detection_reason="Zombie: instance is stopped and last EC2 metric is 45 days old (threshold=30).",
        phase2_action_changed=False,
        blast_radius=0,
        relationship_count=0,
        blast_radius_explanation="No relationships found. Safe to terminate.",
        instance_type="m5.large",
        current_cost_per_hour=0.096,
        waste_per_month=69.12,
    ),
]

# ── Mock S3 Phase 1 results (empty — focus test on EC2 only) ──────────────────
MOCK_S3_PHASE1 = []


def _separator(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def main():
    repo_url = os.environ.get("PHASE3_TERRAFORM_REPO_URL")
    model_key = os.environ.get("PHASE3_MODEL")
    create_pr = os.environ.get("PHASE3_CREATE_PR", "0").strip().lower() in ("1", "true", "yes")

    _separator("TEST: terraform retrieval → LLM → patch → PR")
    print(f"  repo_url   : {repo_url or '(not set — terraform bundle will be empty)'}")
    print(f"  model      : {model_key or '(first model in config)'}")
    print(f"  create_pr  : {create_pr}")
    print(f"  mock EC2 P1: {len(MOCK_EC2_PHASE1)} instances")
    print(f"  mock EC2 P2: {len(MOCK_EC2_PHASE2)} instances")

    # ── Step 1: Run Phase 3 ───────────────────────────────────────────────────
    _separator("STEP 1 — run_phase3_llm()")
    output = run_phase3_llm(
        ec2_phase1_results=MOCK_EC2_PHASE1,
        ec2_phase2_results=MOCK_EC2_PHASE2,
        s3_phase1_results=MOCK_S3_PHASE1,
        model_key=model_key,
    )

    # ── Step 2: Terraform bundle ──────────────────────────────────────────────
    _separator("STEP 2 — Terraform bundle")
    tf_source = output.get("terraform_source", {})
    print(f"  files fetched : {tf_source.get('file_count', 0)}")
    for f in tf_source.get("files", []):
        print(f"    {f}")
    for w in tf_source.get("warnings", []):
        print(f"  WARNING: {w}")

    # ── Step 3: LLM runs ──────────────────────────────────────────────────────
    _separator("STEP 3 — LLM runs")
    for run in output.get("runs", []):
        stype = run.get("scenario_type")
        llm = run.get("llm", {})
        parsed = llm.get("parsed")
        parse_error = llm.get("parse_error")
        print(f"\n  [{stype.upper()}]")
        if parse_error:
            print(f"  parse_error : {parse_error}")
        elif parsed:
            print(f"  verdict     : {parsed.get('verdict')}")
            ds = parsed.get("decision_summary", {})
            print(f"  action      : {ds.get('action')}")
            print(f"  decided_by  : {ds.get('decided_by')}")
            tf_action = parsed.get("terraform_action")
            print(f"  tf_action   : {tf_action}")
            mf = parsed.get("modified_files", [])
            print(f"  modified_files: {len(mf)} file(s)")
            for f in mf:
                print(f"    → {f.get('file_path')}  ({len(f.get('new_content',''))} chars)")

    # ── Step 4: Patch plan ────────────────────────────────────────────────────
    _separator("STEP 4 — Patch plan")
    patch = output.get("patch_plan", {})
    print(f"  pr_title     : {patch.get('pr_title')}")
    print(f"  modified_files: {len(patch.get('modified_files', []))} file(s)")
    for f in patch.get("modified_files", []):
        print(f"    → {f.get('file_path')}  ({f.get('new_content_length')} chars)")
    for w in patch.get("warnings", []):
        print(f"  WARNING: {w}")

    # ── Step 5: PR result ─────────────────────────────────────────────────────
    _separator("STEP 5 — Pull Request")
    pr = output.get("pull_request", {})
    if pr.get("created"):
        print(f"  PR created  : YES")
        print(f"  branch      : {pr.get('branch_name')}")
        print(f"  url         : {pr.get('pr_url')}")
        print(f"  changed     : {pr.get('changed_files')}")
    else:
        print(f"  PR created  : NO")
        print(f"  reason      : {pr.get('reason') or pr.get('errors')}")
    for w in pr.get("warnings", []):
        print(f"  WARNING: {w}")

    # ── Full output dump ──────────────────────────────────────────────────────
    _separator("FULL OUTPUT (phase3_test_output.json)")
    out_path = Path("phase3_test_output.json")
    out_path.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
    print(f"  Written to {out_path.resolve()}")


if __name__ == "__main__":
    main()
