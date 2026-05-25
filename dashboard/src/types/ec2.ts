export type RiskLevel = "Low" | "Medium" | "High" | "Critical"

export type Ec2Finding = {
  instance: string
  region: string
  instanceType: string
  issue: string
  cpuAverage: string
  cpuP95: string
  memoryAverage: string
  recommendation: string
  estimatedSaving: number
  risk: RiskLevel
  status: string
}
