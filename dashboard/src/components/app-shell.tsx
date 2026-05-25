import type { CSSProperties, ReactNode } from "react"

import { AppSidebar } from "@/components/app-sidebar"
import { SiteHeader } from "@/components/site-header"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import type { PageId } from "@/lib/navigation"
import { pageMeta } from "@/lib/navigation"

type AppShellProps = {
  activePage: PageId
  children: ReactNode
}

export function AppShell({ activePage, children }: AppShellProps) {
  return (
    <SidebarProvider
      style={
        {
          "--sidebar-width": "17rem",
          "--header-height": "3.5rem",
        } as CSSProperties
      }
    >
      <AppSidebar activePage={activePage} variant="inset" />
      <SidebarInset>
        <SiteHeader title={pageMeta[activePage].title} />
        <main className="flex-1 bg-slate-50/70 p-4 dark:bg-background md:p-6">
          {children}
        </main>
      </SidebarInset>
    </SidebarProvider>
  )
}
