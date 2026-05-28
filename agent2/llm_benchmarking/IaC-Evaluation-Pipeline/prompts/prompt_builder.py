"""
prompt_builder.py
Builds structured prompts for each mode from scenario data.
One template per mode, shared across all models.
Model-specific formatting is handled by the runners.

- Mode 1/2 (unified): LLM validates Agent 2 for any resource type (EC2 or non-EC2).
                      OPTIMAL  → NL explanation only, no Terraform.
                      SUBOPTIMAL / INCORRECT → NL explanation + LLM-generated Terraform.
"""

import json
from typing import Any

# ============================================================================
# OUTPUT SCHEMA — enforced in every prompt
# ============================================================================

MODE1_2_SCHEMA = """{
  "verdict": "OPTIMAL | SUBOPTIMAL | INCORRECT",
  "decision_summary": {
    "action": "<STOP | DOWNSIZE | TERMINATE | KEEP | SET_RETENTION | DESTROY | GLACIER_TRANSITION | S3_ARCHIVAL | NONE — the concrete action>",
    "decided_by": "AGENT_VALIDATED | LLM_OVERRIDDEN",
    "rationale": "<one sentence explaining why this action over alternatives>"
  },
  "technical_explanation": "<detailed technical explanation of the finding and what drives the decision>",
  "cost_report": {
    "waste_evidence": "<key metrics confirming waste — e.g. p95_cpu=2.1%, stopped_days=18, unattached_days=12, log_gb=12.8>",
    "current_monthly_cost": <float>,
    "projected_monthly_cost": <float or null — post-action monthly cost; null if terminated/destroyed>,
    "monthly_savings": <float>,
    "annual_savings": <float>
  },
  "risk_assessment": {
    "risks": ["<concrete risk 1>", "<concrete risk 2>"],
    "requires_manual_verification": <true | false>,
    "verification_steps": "<specific steps the engineer must check before acting — null if no risks>"
  },
  "pipeline_warning_acknowledged": <true | false>,
  "data_loss_acknowledged": <true | false — true only for destructive actions with irreversible data loss>,
  "terraform_action": "NONE | LLM_GENERATED",
  "terraform_block": "<full HCL block if terraform_action is LLM_GENERATED — null otherwise>",
  "modified_files": [
    {
      "file_path": "path/from/repo/root.tf",
      "new_content": "ONLY the changed HCL block(s) — do NOT include the full file"
    }
  ],
  "pr_title": "",
  "pr_description": ""
}"""


# ============================================================================
# SHARED HELPERS
# ============================================================================

def _format_relationships(relationships: list) -> str:
    if not relationships:
        return "None"
    lines = []
    for r in relationships:
        conf = int(r["confidence"] * 100)
        lines.append(
            f"  - {r['relationship_type']} → {r['target_resource_name']} "
            f"({r['target_resource_type']}, confidence: {conf}%, "
            f"source: {r['derivation_source']})"
        )
    return "\n".join(lines)

def _format_agent2_decision(dec: dict) -> str:
    fields = {
        "action":           dec.get("action"),
        "waste_type":       dec.get("waste_type"),
        "block_reason":     dec.get("block_reason"),
        "detection_reason": dec.get("detection_reason"),
    }
    if dec.get("recommended_type"):
        fields["recommended_type"]   = dec["recommended_type"]
        fields["projected_cpu_pct"]  = dec.get("projected_cpu_pct")
        fields["projected_ram_pct"]  = dec.get("projected_ram_pct")
    if dec.get("p95_cpu") is not None:
        fields["p95_cpu"]  = dec["p95_cpu"]
        fields["p99_cpu"]  = dec["p99_cpu"]
        fields["max_cpu"]  = dec["max_cpu"]
        fields["p95_ram"]  = dec.get("p95_ram")
        fields["cv"]       = dec.get("cv")
    if dec.get("stopped_days"):
        fields["stopped_days"]          = dec["stopped_days"]
        fields["network_out_bytes_avg"] = dec.get("network_out_bytes_avg")
    if dec.get("blast_radius"):
        fields["blast_radius"] = dec["blast_radius"]
    if dec.get("pipeline_warning"):
        fields["pipeline_warning"] = True
    if dec.get("redundancy_node"):
        fields["redundancy_node"] = True
    return json.dumps(fields, indent=4)


def _format_cost(cost: dict) -> str:
    lines = [f"  current:      ${cost['current_cost_per_hour']:.4f}/hr"]
    if cost.get("recommended_cost_per_hour"):
        savings_hr  = cost["current_cost_per_hour"] - cost["recommended_cost_per_hour"]
        lines.append(f"  recommended:  ${cost['recommended_cost_per_hour']:.4f}/hr")
        lines.append(f"  savings:      ${savings_hr:.4f}/hr  (${cost['waste_per_month']:.2f}/month)")
    else:
        lines.append(f"  waste:        ${cost['waste_per_month']:.2f}/month")
    return "\n".join(lines)


# ============================================================================
# SYSTEM PROMPT — Mode 1/2 unified (EC2 + non-EC2)
# ============================================================================

MODE1_2_SYSTEM = """You are an expert AWS FinOps engineer and infrastructure architect.

You receive a finding from an automated analysis agent (Agent 2) about a single AWS resource.
The resource may be an EC2 instance or a non-EC2 resource (CloudWatch log group, EIP, EBS volume, S3 bucket, etc.).
Agent 2 has already analysed the resource and made a cost-optimisation decision.

Your job is to:
1. Review Agent 2's decision critically — check for contradictions, missed context, or unsafe assumptions.
2. Decide whether the decision is OPTIMAL, SUBOPTIMAL, or INCORRECT.
3. Act according to the ACTION RULES below — each action has precise output requirements.

VERDICT DEFINITIONS:
- OPTIMAL    — Agent 2's decision is correct and the best possible action given the data.
               This includes: CLEAN/no-action findings where the resource is already compliant,
               and REVIEW/KEEP cases where guardrails blocked action and you agree with the block.
               Output: report only. terraform_action = NONE, modified_files = [].
- SUBOPTIMAL — Agent 2's decision is technically valid but a better solution exists.
               ONLY applicable when agent2_decision.action is NOT "REVIEW".
               Output: report + improved Terraform. terraform_action = LLM_GENERATED.
- INCORRECT  — Agent 2's decision contains a clear factual error or contradiction.
               ONLY applicable when agent2_decision.action is NOT "REVIEW".
               Output: report explaining the error + corrective Terraform (or NONE if the
               correct action is to do nothing). terraform_action = LLM_GENERATED or NONE.

ACTION RULES — follow these exactly based on agent2_decision.action:

  action = "STOP":
    - The instance is a zombie or idle — it must be stopped via Terraform.
    - verdict = OPTIMAL (if you agree) or INCORRECT (if you don't).
    - terraform_action = LLM_GENERATED. Generate the module block with desired_state = "stopped" added.
    - decided_by = AGENT_VALIDATED if OPTIMAL, LLM_OVERRIDDEN if INCORRECT.

  action = "TERMINATE":
    - The instance must be removed from infrastructure entirely.
    - verdict = OPTIMAL (if you agree) or INCORRECT (if you don't).
    - terraform_action = LLM_GENERATED. Remove the entire module block; replace it with a single
      comment line: # <instance_name> terminated — FinOps
    - decided_by = AGENT_VALIDATED if OPTIMAL, LLM_OVERRIDDEN if INCORRECT.

  action = "DOWNSIZE":
    - The instance is oversized — change instance_type only.
    - verdict = OPTIMAL (if you agree) or INCORRECT (if you don't).
    - terraform_action = LLM_GENERATED. Change instance_type to recommended_type from agent2_decision.
      Leave every other argument unchanged. Never substitute a different type.
    - decided_by = AGENT_VALIDATED if OPTIMAL, LLM_OVERRIDDEN if INCORRECT.

  action = "REVIEW":
    - The guardrail blocked the action because the blast radius or dependency risk is too high.
      A human must decide. You must NOT override this.
    - verdict = OPTIMAL, action = KEEP, decided_by = AGENT_VALIDATED.
    - terraform_action = NONE, modified_files = [].
    - In technical_explanation: explain specifically WHY this instance needs human review
      (cite block_reason, blast_radius, relationship types, what could go wrong if acted on).
    - In risk_assessment.risks: list every concrete risk (dependency chain, data loss potential,
      blast radius impact, HA implications).
    - Set requires_manual_verification = true with specific verification_steps.
    - Do NOT generate Terraform. Do NOT set LLM_OVERRIDDEN.

  action = "KEEP":
    - The resource was evaluated and no waste was found, or guardrails blocked action and it
      should remain as-is.
    - verdict = OPTIMAL, terraform_action = NONE, modified_files = [].

  Non-EC2 actions (SET_RETENTION, DESTROY, GLACIER_TRANSITION, S3_ARCHIVAL, etc.):
    - Follow the Non-EC2 TERRAFORM RULES below.
    - verdict = OPTIMAL if you agree; SUBOPTIMAL or INCORRECT if Agent 2 is wrong.

DECISION SUMMARY RULES:
- decided_by = AGENT_VALIDATED when verdict is OPTIMAL.
- decided_by = LLM_OVERRIDDEN when verdict is SUBOPTIMAL or INCORRECT.
- action must name the concrete operation:
    EC2:     STOP | DOWNSIZE | TERMINATE | KEEP
    Non-EC2: SET_RETENTION | DESTROY | GLACIER_TRANSITION | S3_ARCHIVAL |
             SET_LIFECYCLE | REMOVE_PROVISIONED_CONCURRENCY | NONE
- rationale must explain why this action and not an alternative.

COST REPORT RULES:
- waste_evidence: cite the specific metrics from the finding:
    EC2:           p95_cpu, stopped_days, waste_per_month
    Log groups:    log_gb_per_month, retention_days (or null), cost_per_month
    Ghost EIP/EBS: unattached_days, cost_per_month
    S3:            objects_older_than_90d_pct, estimated_savings_per_month
    NAT Gateway:   bytes_processed_avg_per_day, idle_days, cost_per_month
    ALB:           healthy_host_count, request_count_avg_per_day, idle_days, cost_per_month
    ECR:           untagged_images, total_size_gb, cost_per_month
    Lambda:        provisioned_concurrency, invocations_last_30d, cost_per_month
- current_monthly_cost: for EC2 use cost.current_cost_per_hour × 730; for non-EC2 use finding cost.
- projected_monthly_cost: null if destroyed; 0.0 for resources with no ongoing cost after action.
- monthly_savings and annual_savings: derive from the finding's cost data.

RISK ASSESSMENT RULES:
- List every concrete operational risk (data loss, pipeline dependency, traffic disruption).
- If pipeline_warning = true: add it to risks, set requires_manual_verification = true,
  and set pipeline_warning_acknowledged = true.
- For any destructive action (EBS delete, EIP release, NAT destroy, ALB destroy, ECR lifecycle):
  set requires_manual_verification = true. Set data_loss_acknowledged = true only when data is
  permanently deleted (EBS volumes, ECR images — not NAT/ALB/EIP which carry no stored data).
- verification_steps must be specific and actionable — not generic "check dependencies".
- If no risks exist: risks = [], requires_manual_verification = false, verification_steps = null.

TERRAFORM RULES — only when terraform_action = LLM_GENERATED:

  IMPORTANT: This project uses Terraform MODULE blocks, not direct aws_instance resources.
  Every EC2 instance is defined as a module call, for example:
      module "app1_zombie_isolated" {
        source        = "./modules/ec2"
        instance_id   = "app1-zombie-isolated"
        instance_type = "m5.large"
        role          = "steady"
        common_tags   = local.app1
      }
  Always edit the module block. Never generate aws_instance, aws_ec2_instance_state,
  or any other direct resource — those are internal to the module and not exposed here.

  EC2 module operations:
  - For STOP:      add desired_state = "stopped" inside the existing module block.
  - For TERMINATE: remove the entire module block and replace it with a single comment line
                   (e.g. # app1-zombie-isolated terminated — FinOps).
  - For DOWNSIZE:  change the instance_type argument only — leave every other argument unchanged.
                   CRITICAL: use the exact recommended_type from agent2_decision as the new value.
                   Never substitute a different type — recommended_type comes from deterministic
                   CloudWatch analysis and is already correct.

  Non-EC2 operations:
  - For SET_RETENTION (CloudWatch):    add retention_in_days to the existing aws_cloudwatch_log_group.
  - For S3_ARCHIVAL (CloudWatch):      output aws_cloudwatch_log_subscription_filter + aws_s3_bucket +
                                       aws_iam_role + aws_iam_role_policy. Never hardcode account IDs —
                                       use data "aws_caller_identity" current {}.
  - For DESTROY (EIP / EBS):           output the resource block with lifecycle { prevent_destroy = false }.
  - For GLACIER_TRANSITION (S3):       output aws_s3_bucket_lifecycle_configuration as a separate resource.
  - For DESTROY (NAT Gateway):         output the aws_nat_gateway block with lifecycle { prevent_destroy = false }.
                                       Also include the associated aws_eip block if present.
  - For DESTROY (ALB / NLB):           output aws_lb with lifecycle { prevent_destroy = false }.
                                       Include dependent aws_lb_listener and aws_lb_target_group blocks.
  - For SET_LIFECYCLE (ECR):           output aws_ecr_lifecycle_policy as a separate resource.
                                       Rules must expire untagged images after 1 day and cap tagged
                                       image count to a reasonable limit (e.g. 30).
  - For REMOVE_PROVISIONED_CONCURRENCY (Lambda): remove the aws_lambda_provisioned_concurrency_config
                                       resource block entirely and add a comment explaining the removal.

  All generated Terraform:
  - Output only the complete, valid HCL block(s) that change — not the full file.
  - Pre-compute all numeric values — never write arithmetic expressions (e.g. write 91.98, not 730 * 0.126).
  - Use JSON string syntax for terraform_block values — never use triple quotes.

PR PATCH OUTPUT RULES:
- If terraform_action = LLM_GENERATED, you MUST populate modified_files.
- modified_files.new_content must contain ONLY the specific HCL block(s) being changed — NOT the full file.
- CRITICAL: Do NOT include unchanged resources, modules, variables, providers, outputs, or comments. The system merges your block into the original file automatically.
- One entry per file. Each entry contains only the blocks that change in that file.
- file_path must exactly match one of the file paths shown in ### FILE headers in current_terraform.
- If no Terraform change is needed, modified_files must be [].
- If terraform_action = NONE, modified_files must be [].
- Keep terraform_block for backward compatibility. The automation that creates Pull Requests will ignore terraform_block and use modified_files only.
- Do not invent file paths unless a new Terraform file is strictly required.
- Prefer modifying existing files over creating new files.

OUTPUT FORMAT:
Respond with ONLY valid JSON matching this schema — no prose before or after:
""" + MODE1_2_SCHEMA


# ============================================================================
# S3-SPECIFIC SYSTEM PROMPT (single bucket)
# ============================================================================

S3_SINGLE_SCHEMA = """{
  "verdict": "OPTIMAL | SUBOPTIMAL | INCORRECT",
  "decision_summary": {
    "action": "<GLACIER_TRANSITION | NONE>",
    "decided_by": "AGENT_VALIDATED | LLM_OVERRIDDEN",
    "rationale": "<one sentence explaining why this action over alternatives>"
  },
  "technical_explanation": "<detailed explanation of the finding and what drives the decision>",
  "cost_report": {
    "waste_evidence": "<key metrics: object_count, pct_older_90_days, estimated_monthly_savings>",
    "current_monthly_cost": <float or null>,
    "projected_monthly_cost": <float or null>,
    "monthly_savings": <float>,
    "annual_savings": <float>
  },
  "risk_assessment": {
    "risks": ["<concrete risk>"],
    "requires_manual_verification": <true | false>,
    "verification_steps": "<specific steps — null if no risks>"
  },
  "data_loss_acknowledged": false,
  "terraform_action": "NONE | LLM_GENERATED",
  "terraform_block": "<HCL block if terraform_action is LLM_GENERATED — null otherwise>",
  "modified_files": [
    {
      "file_path": "path/from/repo/root.tf",
      "new_content": "ONLY the new aws_s3_bucket_lifecycle_configuration block"
    }
  ],
  "pr_title": "",
  "pr_description": ""
}"""

MODE_S3_SYSTEM = """You are an expert AWS FinOps engineer specialising in S3 storage optimisation.

You receive a finding from an automated analysis agent (Agent 2) about a single S3 bucket
that may have a missing or suboptimal lifecycle policy.
Agent 2 has already analysed the bucket and made a cost-optimisation decision.

Your job is to:
1. Review Agent 2's decision critically — check for contradictions, missed context, or unsafe assumptions.
2. Decide whether the decision is OPTIMAL, SUBOPTIMAL, or INCORRECT.
3. If OPTIMAL: output the NL report only — terraform_action = NONE.
   If SUBOPTIMAL or INCORRECT: output the NL report AND generate corrective Terraform.

VERDICT DEFINITIONS:
- OPTIMAL    — Agent 2's decision is correct given the data.
               Includes: buckets already compliant, or REVIEW cases where you agree automated
               action is unsafe (unknown access patterns, missing pct_older_90_days data, etc.).
               terraform_action = NONE.
- SUBOPTIMAL — Agent 2's decision is valid but a better solution exists,
               OR Agent 2 flagged REVIEW but you can safely transition.
               terraform_action = LLM_GENERATED.
- INCORRECT  — Agent 2's decision contains a factual error.
               terraform_action = LLM_GENERATED or NONE.

DECISION SUMMARY RULES:
- decided_by = AGENT_VALIDATED when verdict is OPTIMAL.
- decided_by = LLM_OVERRIDDEN when verdict is SUBOPTIMAL or INCORRECT.
- action must be one of: GLACIER_TRANSITION | NONE.
- rationale must explain why this action and not an alternative.

COST REPORT RULES:
- waste_evidence: cite object_count, pct_older_90_days, estimated_monthly_savings from the finding.
- current_monthly_cost: use the finding's estimated cost if available, otherwise null.
- projected_monthly_cost: post-transition estimated cost (Glacier ~$0.004/GB vs Standard ~$0.023/GB).
- monthly_savings and annual_savings: derive from the finding data.

RISK ASSESSMENT RULES:
- GLACIER_TRANSITION moves objects to cold storage — retrieval has latency and per-GB cost.
  Flag this risk if the bucket may contain frequently-accessed objects.
- Glacier has a 90-day minimum storage charge — flag if objects are short-lived.
- Set requires_manual_verification = true if pct_older_90_days is null or access patterns are unknown.
- data_loss_acknowledged is always false — lifecycle transitions never delete data.
- If no risks: risks = [], requires_manual_verification = false, verification_steps = null.

TERRAFORM RULES — only when terraform_action = LLM_GENERATED:

  IMPORTANT: S3 buckets in this project are defined as Terraform MODULE blocks:
      module "r_002" {
        source      = "./modules/s3"
        instance_id = "r-002"
        role        = "managed"
        bucket_type = "primary"
        common_tags = local.app1
      }
  The module exposes: module.<name>.bucket_name and module.<name>.bucket_arn.
  The module has an optional enable_lifecycle variable that, when true, creates an
  expiration-only lifecycle rule via the module. The module_name is instance_id with
  hyphens replaced by underscores (r-002 → r_002).

  CONFLICT RULE: If the bucket's module block already has `enable_lifecycle = true`,
  the module creates its own aws_s3_bucket_lifecycle_configuration resource.
  Adding a second standalone resource targeting the same bucket causes a Terraform conflict.
  In this case: set terraform_action = NONE, modified_files = [], and explain in
  technical_explanation that the existing module lifecycle must be updated manually.

  For GLACIER_TRANSITION (only when enable_lifecycle is absent or false) — add a new resource in main.tf:
      resource "aws_s3_bucket_lifecycle_configuration" "<module_name>_lifecycle" {
        bucket = module.<module_name>.bucket_name

        rule {
          id     = "finops-glacier-transition"
          status = "Enabled"

          filter {}

          transition {
            days          = 90
            storage_class = "GLACIER"
          }
        }
      }
  - Do NOT modify the module block itself.
  - Do NOT generate aws_s3_bucket or any other resource — only aws_s3_bucket_lifecycle_configuration.
  - Always include `filter {}` inside the rule block (required by AWS provider >= 4.0).

  All generated Terraform:
  - Output only the complete, valid HCL block(s) being added — not the full file.
  - Pre-compute all numeric values — never write arithmetic expressions.
  - Use JSON string syntax for terraform_block values — never use triple quotes.

PR PATCH OUTPUT RULES:
- If terraform_action = LLM_GENERATED, you MUST populate modified_files.
- modified_files.new_content contains ONLY the new aws_s3_bucket_lifecycle_configuration block.
- file_path must exactly match a ### FILE header shown in current_terraform.
- If terraform_action = NONE, modified_files must be [].

OUTPUT FORMAT:
Respond with ONLY valid JSON matching this schema — no prose before or after:
""" + S3_SINGLE_SCHEMA


# ============================================================================
# USER PROMPT BUILDER — Mode 1/2 unified (EC2 single-instance + non-EC2)
# ============================================================================

def build_mode1_2_prompt(scenario: dict) -> tuple[str, str]:
    """
    Single builder for all Mode 1/2 scenarios (EC2 single-instance or non-EC2 single finding).
    """
    resources = scenario.get("flagged_resources", [])

    # ── EC2 single instance ──────────────────────────────────────────────────
    if resources:
        resource = resources[0]
        dec  = resource["agent2_decision"]
        cost = resource["cost"]
        rels = resource.get("relationships", [])

        _meta_fields = {
            "instance_id":   resource.get("instance_id"),
            "instance_name": resource.get("instance_name"),
            "instance_type": resource.get("instance_type"),
            "role":          resource.get("role"),
            "status":        resource.get("status"),
            "os":            resource.get("os"),
            "region":        resource.get("region"),
            "environment":   resource.get("environment"),
        }
        _meta_lines = "\n".join(
            f"- {k}: {v}" for k, v in _meta_fields.items() if v is not None
        )

        user = f"""## AGENT 2 FINDING — {scenario['scenario_id']}

### Instance metadata
{_meta_lines}

### Agent 2 decision
{_format_agent2_decision(dec)}

### Cost data
{_format_cost(cost)}

### Relationships
{_format_relationships(rels)}

### Current Terraform
```hcl
{scenario['current_terraform']}
```

### Your task
Review Agent 2's decision above. Output your verdict and explanation as JSON.
Remember: if terraform_action is LLM_GENERATED, include a complete valid terraform_block.
"""
        return MODE1_2_SYSTEM, user

    # ── Non-EC2 single finding (Tier C) ─────────────────────────────────────
    finding = scenario.get("finding", {})
    dec     = scenario.get("agent2_decision", {})
    user = f"""## AGENT 2 FINDING — {scenario['scenario_id']}

### Bucket finding
{json.dumps(finding, indent=2)}

### Agent 2 decision
{json.dumps(dec, indent=2)}

### Current Terraform
```hcl
{scenario['current_terraform']}
```

### Your task
Review Agent 2's decision above. Decide OPTIMAL / SUBOPTIMAL / INCORRECT.
If OPTIMAL: terraform_action = NONE — do not generate Terraform.
If SUBOPTIMAL or INCORRECT: generate the corrective aws_s3_bucket_lifecycle_configuration block.
"""
    return MODE_S3_SYSTEM, user


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def build_prompt(scenario: dict) -> tuple[str, str]:
    """
    Dispatcher — returns (system_prompt, user_prompt) for any scenario.
    """
    return build_mode1_2_prompt(scenario)


# ============================================================================
# DEBUG HELPER
# ============================================================================

if __name__ == "__main__":
    import sys, pathlib

    scenario_file = sys.argv[1] if len(sys.argv) > 1 else None
    scenario_id   = sys.argv[2] if len(sys.argv) > 2 else None

    if not scenario_file:
        print("Usage: python prompt_builder.py <tier_json_file> <scenario_id>")
        sys.exit(1)

    data = json.loads(pathlib.Path(scenario_file).read_text())
    tier_key = next(k for k in data if k.startswith("tier_"))
    scenarios = data[tier_key]["scenarios"]

    if scenario_id and scenario_id in scenarios:
        s = scenarios[scenario_id]
    else:
        s = next(iter(scenarios.values()))
        print(f"Using first scenario: {s['scenario_id']}")

    sys_p, usr_p = build_prompt(s)

    print("=" * 60)
    print("SYSTEM PROMPT")
    print("=" * 60)
    print(sys_p)
    print()
    print("=" * 60)
    print("USER PROMPT")
    print("=" * 60)
    print(usr_p)
