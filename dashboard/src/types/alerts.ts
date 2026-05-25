export type AlertSeverity = "Info" | "Warning" | "High" | "Critical"

export type Alert = {
  severity: AlertSeverity
  type: string
  message: string
  resource: string
  status: string
  createdAt: string
}
