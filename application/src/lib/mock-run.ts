import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'fs';
import path from 'path';

export const MOCK_RUN_ID = -1;

const now = '2026-05-27T15:30:00.000Z';
const mockStateDir = path.join(process.cwd(), '.analysis');
const mockPreviewPath = path.join(mockStateDir, 'mock-preview.json');

const originalMain = `module "app1_worker_oversized_risky" {
  source        = "./modules/ec2"
  instance_id   = "app1-worker-oversized-risky"
  instance_type = "c5.2xlarge"
  role          = "steady"
}

module "app2_reporting_primary" {
  source        = "./modules/ec2"
  instance_id   = "app2-reporting-primary"
  instance_type = "m5.xlarge"
  role          = "dependant_primary"
}

module "app2_bursty_oversized" {
  source        = "./modules/ec2"
  instance_id   = "app2-bursty-oversized"
  instance_type = "t3.xlarge"
  role          = "bursty"
}

module "app2_steady_oversized_safe" {
  source        = "./modules/ec2"
  instance_id   = "app2-steady-oversized-safe"
  instance_type = "c5.xlarge"
  role          = "steady"
}`;

const patchedMain = originalMain
  .replace('instance_type = "m5.xlarge"', 'instance_type = "m5.large"')
  .replace('instance_type = "t3.xlarge"', 'instance_type = "t3.large"')
  .replace('instance_type = "c5.xlarge"', 'instance_type = "c5.large"');

function scenario(instanceName: string, instanceType: string, action: string, recommendedType: string, reason: string) {
  return {
    flagged_resources: [
      {
        instance_id: instanceName,
        instance_name: instanceName,
        instance_type: instanceType,
        agent2_decision: {
          action,
          recommended_type: recommendedType,
          detection_reason: reason,
        },
      },
    ],
  };
}

export const mockRun = {
  id: MOCK_RUN_ID,
  workspace_key: 'mock-fixture',
  status: 'completed',
  started_at: now,
  completed_at: now,
  phase3_model_key: 'replayed-successful-output',
  error_message: null,
  ec2_count: 6,
  s3_count: 2,
  ec2_savings: '727.34',
  s3_savings: '0',
};

export const mockPhases = {
  ec2Phase1: [
    {
      id: 1,
      resource_id: 1,
      resource_name: 'app2-bursty-oversized',
      role: 'bursty',
      action: 'DOWNSIZE',
      waste_type: 'oversized',
      current_instance_type: 't3.xlarge',
      recommended_type: 't3.large',
      waste_per_month: 138.24,
      detection_reason: 'Low sustained CPU and memory on bursty workload.',
      metrics: {},
      region: 'eu-west-1',
      avg_cpu: 8.1,
      avg_ram: 21.4,
      telemetry_p95_cpu: 18.2,
    },
    {
      id: 2,
      resource_id: 2,
      resource_name: 'app2-steady-oversized-safe',
      role: 'steady',
      action: 'DOWNSIZE',
      waste_type: 'oversized',
      current_instance_type: 'c5.xlarge',
      recommended_type: 'c5.large',
      waste_per_month: 72.91,
      detection_reason: 'Steady isolated instance has safe utilization headroom.',
      metrics: {},
      region: 'eu-west-1',
      avg_cpu: 11.8,
      avg_ram: 33.0,
      telemetry_p95_cpu: 24.6,
    },
    {
      id: 3,
      resource_id: 3,
      resource_name: 'app1-worker-oversized-risky',
      role: 'steady',
      action: 'REVIEW',
      waste_type: 'oversized',
      current_instance_type: 'c5.2xlarge',
      recommended_type: 'c5.large',
      waste_per_month: 276.48,
      detection_reason: 'Oversized but writes to production data path, so Phase 2 keeps review.',
      metrics: {},
      region: 'eu-west-1',
      avg_cpu: 13.4,
      avg_ram: 38.2,
      telemetry_p95_cpu: 28.8,
    },
    {
      id: 4,
      resource_id: 4,
      resource_name: 'app2-stopped-zombie',
      role: 'steady',
      action: 'TERMINATE',
      waste_type: 'stopped_zombie',
      current_instance_type: 'm5.large',
      recommended_type: null,
      waste_per_month: 69.12,
      detection_reason: 'Stopped long enough to be considered abandoned.',
      metrics: {},
      region: 'eu-west-1',
      avg_cpu: null,
      avg_ram: null,
      telemetry_p95_cpu: null,
    },
  ],
  s3Phase1: [
    {
      id: 10,
      resource_id: 10,
      bucket_name: 'app1-logs-bucket',
      action: 'CLEAN',
      waste_type: 'old_objects',
      detection_reason: 'Old log objects without lifecycle policy.',
      recommended_action: 'Add lifecycle transition/expiration.',
      metrics: { estimated_monthly_savings: 0 },
      region: 'eu-west-1',
      inv_object_count: 5,
      inv_size_bytes: 1200000000,
    },
  ],
  ec2Phase2: [
    {
      id: 1,
      instance_name: 'app2-bursty-oversized',
      role: 'bursty',
      waste_type: 'oversized',
      phase1_action: 'DOWNSIZE',
      action: 'DOWNSIZE',
      phase2_action_changed: false,
      phase2_action_reason: null,
      blast_radius: 1,
      relationship_count: 1,
      blast_radius_explanation: 'Low dependency count; resize is safe.',
      waste_per_month: 138.24,
      skip_write: false,
      block_reason: null,
    },
    {
      id: 2,
      instance_name: 'app1-worker-oversized-risky',
      role: 'steady',
      waste_type: 'oversized',
      phase1_action: 'DOWNSIZE',
      action: 'REVIEW',
      phase2_action_changed: true,
      phase2_action_reason: 'Writes to production bucket and backs up logs; review required.',
      blast_radius: 5,
      relationship_count: 3,
      blast_radius_explanation: 'Multiple production relationships.',
      waste_per_month: 276.48,
      skip_write: false,
      block_reason: null,
    },
  ],
};

export const mockLlm = {
  ec2Waste: [
    {
      id: 1001,
      resource_id: 1,
      resource_name: 'app2-bursty-oversized',
      waste_type: 'oversized',
      action: 'DOWNSIZE',
      verdict: 'APPROVE',
      decision_action: 'DOWNSIZE',
      decided_by: 'LLM_VALIDATED',
      decision_rationale: 'The utilization pattern supports one-size downscaling while preserving burst capacity.',
      technical_explanation: 'LLM replay fixture from the latest successful analysis output.',
      cost_report: { monthly_savings: 138.24 },
      risk_assessment: { requires_manual_verification: false },
      terraform_action: 'INSTANCE_TYPE_PATCH',
      terraform_block: null,
      parse_error: null,
      scenario_json: scenario('app2-bursty-oversized', 't3.xlarge', 'DOWNSIZE', 't3.large', 'Low sustained CPU and memory on bursty workload.'),
    },
    {
      id: 1002,
      resource_id: 2,
      resource_name: 'app2-steady-oversized-safe',
      waste_type: 'oversized',
      action: 'DOWNSIZE',
      verdict: 'APPROVE',
      decision_action: 'DOWNSIZE',
      decided_by: 'LLM_VALIDATED',
      decision_rationale: 'Steady instance has enough CPU/RAM headroom for c5.large.',
      technical_explanation: 'Validated as a direct instance_type replacement.',
      cost_report: { monthly_savings: 72.91 },
      risk_assessment: { requires_manual_verification: false },
      terraform_action: 'INSTANCE_TYPE_PATCH',
      terraform_block: null,
      parse_error: null,
      scenario_json: scenario('app2-steady-oversized-safe', 'c5.xlarge', 'DOWNSIZE', 'c5.large', 'Safe low-blast-radius downsize candidate.'),
    },
    {
      id: 1003,
      resource_id: 3,
      resource_name: 'app2-reporting-primary',
      waste_type: 'oversized',
      action: 'DOWNSIZE',
      verdict: 'APPROVE',
      decision_action: 'DOWNSIZE',
      decided_by: 'LLM_VALIDATED',
      decision_rationale: 'Reporting workload can move from m5.xlarge to m5.large with monitored rollout.',
      technical_explanation: 'Validated as a direct instance_type replacement.',
      cost_report: { monthly_savings: 138.24 },
      risk_assessment: { requires_manual_verification: true },
      terraform_action: 'INSTANCE_TYPE_PATCH',
      terraform_block: null,
      parse_error: null,
      scenario_json: scenario('app2-reporting-primary', 'm5.xlarge', 'DOWNSIZE', 'm5.large', 'Primary reporting instance has consistent spare capacity.'),
    },
    {
      id: 1004,
      resource_id: 4,
      resource_name: 'app1-worker-oversized-risky',
      waste_type: 'oversized',
      action: 'REVIEW',
      verdict: 'REVIEW',
      decision_action: 'REVIEW',
      decided_by: 'LLM_VALIDATED',
      decision_rationale: 'Downsize is technically valid, but production writes make this a review candidate.',
      technical_explanation: 'The replacement can be previewed, but rollout should be approved by an operator.',
      cost_report: { monthly_savings: 276.48 },
      risk_assessment: { requires_manual_verification: true },
      terraform_action: 'INSTANCE_TYPE_PATCH',
      terraform_block: null,
      parse_error: null,
      scenario_json: scenario('app1-worker-oversized-risky', 'c5.2xlarge', 'REVIEW', 'c5.large', 'Production data relationships require review.'),
    },
    {
      id: 1005,
      resource_id: 5,
      resource_name: 'app2-stopped-zombie',
      waste_type: 'stopped_zombie',
      action: 'TERMINATE',
      verdict: 'REVIEW',
      decision_action: 'TERMINATE',
      decided_by: 'AGENT_GUARDRAIL',
      decision_rationale: 'Stopped zombie should be handled as an operational cleanup reminder, not code preview.',
      technical_explanation: 'No Terraform instance_type patch is produced for destructive actions.',
      cost_report: { monthly_savings: 69.12 },
      risk_assessment: { requires_manual_verification: true },
      terraform_action: 'OPERATIONAL_REMINDER',
      terraform_block: null,
      parse_error: null,
      scenario_json: scenario('app2-stopped-zombie', 'm5.large', 'TERMINATE', '', 'Stopped zombie candidate.'),
    },
  ],
  s3Waste: [],
};

export const mockPreview = {
  id: MOCK_RUN_ID,
  run_id: MOCK_RUN_ID,
  source_repo_url: 'https://github.com/Nour-Ben-Hadid/finops-infra.git',
  source_ref: 'main',
  source_subdir: null,
  pr_title: 'Apply EC2 instance type optimizations',
  pr_description: [
    'User-selected EC2 resize changes:',
    '- app2-bursty-oversized: t3.xlarge -> t3.large',
    '- app2-steady-oversized-safe: c5.xlarge -> c5.large',
    '- app2-reporting-primary: m5.xlarge -> m5.large',
  ].join('\n'),
  status: 'pending',
  modified_files: [
    {
      file_path: 'main.tf',
      original_content: originalMain,
      original_content_available: true,
      new_content: patchedMain,
    },
  ],
  warnings: ['Mock replay mode: no LLM provider or backend pipeline was called.'],
  validation_errors: [],
  approval_note: null,
  approved_by: null,
  rejected_by: null,
  branch_name: null,
  pr_url: null,
  pr_errors: [],
  created_at: now,
  updated_at: now,
  approved_at: null,
  rejected_at: null,
};

export function getMockPreview() {
  if (!existsSync(mockPreviewPath)) return mockPreview;
  try {
    return JSON.parse(readFileSync(mockPreviewPath, 'utf8'));
  } catch {
    return mockPreview;
  }
}

export function setMockPreview(preview: any) {
  mkdirSync(mockStateDir, { recursive: true });
  writeFileSync(mockPreviewPath, JSON.stringify(preview, null, 2), 'utf8');
  return preview;
}

export function resetMockPreview() {
  return setMockPreview(mockPreview);
}
