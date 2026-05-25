export type PipelineRun = {
  runId: string
  status: string
  startedAt: string
  completedAt: string
  duration: string
  ec2Findings: number
  s3Findings: number
  blocked: number
  phase3ParseErrors: number
  totalSavings: number
}
