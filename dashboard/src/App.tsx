import { useEffect, useState, type ComponentType } from "react"

import { AppShell } from "@/components/app-shell"
import { pageFromHash, type PageId } from "@/lib/navigation"
import { AlertsPage } from "@/pages/alerts-page"
import { Ec2FindingsPage } from "@/pages/ec2-findings-page"
import { GuardrailsPage } from "@/pages/guardrails-page"
import { OverviewPage } from "@/pages/overview-page"
import { Phase3ReviewPage } from "@/pages/phase3-review-page"
import { RunsHistoryPage } from "@/pages/runs-history-page"
import { S3FindingsPage } from "@/pages/s3-findings-page"

const pages: Record<PageId, ComponentType> = {
  overview: OverviewPage,
  "ec2-findings": Ec2FindingsPage,
  "s3-findings": S3FindingsPage,
  guardrails: GuardrailsPage,
  "phase3-review": Phase3ReviewPage,
  alerts: AlertsPage,
  "runs-history": RunsHistoryPage,
}

function App() {
  const [activePage, setActivePage] = useState<PageId>(() => pageFromHash(window.location.hash))

  useEffect(() => {
    if (!window.location.hash) {
      window.history.replaceState(null, "", "#/overview")
    }

    const updatePage = () => setActivePage(pageFromHash(window.location.hash))
    window.addEventListener("hashchange", updatePage)
    return () => window.removeEventListener("hashchange", updatePage)
  }, [])

  const Page = pages[activePage]

  return (
    <AppShell activePage={activePage}>
      <Page />
    </AppShell>
  )
}

export default App
