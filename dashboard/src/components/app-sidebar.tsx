import type { ComponentProps, ComponentType, SVGProps } from "react"
import {
  BellIcon,
  BotIcon,
  DatabaseIcon,
  HistoryIcon,
  LayoutDashboardIcon,
  ServerIcon,
  ShieldAlertIcon,
} from "lucide-react"

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"
import type { PageId } from "@/lib/navigation"

type NavItem = {
  id: PageId
  title: string
  icon: ComponentType<SVGProps<SVGSVGElement>>
}

const navItems: NavItem[] = [
  { id: "overview", title: "Overview", icon: LayoutDashboardIcon },
  { id: "ec2-findings", title: "EC2 Findings", icon: ServerIcon },
  { id: "s3-findings", title: "S3 Findings", icon: DatabaseIcon },
  { id: "guardrails", title: "Guardrails", icon: ShieldAlertIcon },
  { id: "phase3-review", title: "Phase 3 Review", icon: BotIcon },
  { id: "alerts", title: "Alerts", icon: BellIcon },
  { id: "runs-history", title: "Runs History", icon: HistoryIcon },
]

type AppSidebarProps = ComponentProps<typeof Sidebar> & {
  activePage: PageId
}

export function AppSidebar({ activePage, ...props }: AppSidebarProps) {
  return (
    <Sidebar collapsible="offcanvas" {...props}>
      <SidebarHeader className="border-b border-sidebar-border p-4">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton asChild size="lg" className="px-0 hover:bg-transparent">
              <a href="#/overview">
                <div className="flex size-9 items-center justify-center rounded-lg bg-emerald-600 text-white">
                  <span className="text-sm font-semibold">PFA</span>
                </div>
                <div className="grid flex-1 text-left text-sm leading-tight">
                  <span className="font-semibold">FinOps Control</span>
                  <span className="text-xs text-muted-foreground">Optimization dashboard</span>
                </div>
              </a>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Optimization</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {navItems.map((item) => {
                const Icon = item.icon
                return (
                  <SidebarMenuItem key={item.id}>
                    <SidebarMenuButton
                      asChild
                      isActive={activePage === item.id}
                      tooltip={item.title}
                    >
                      <a href={`#/${item.id}`}>
                        <Icon />
                        <span>{item.title}</span>
                      </a>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                )
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="border-t border-sidebar-border p-4">
        <div className="rounded-lg bg-sidebar-accent p-3">
          <p className="text-xs font-medium">Mock data mode</p>
          <p className="mt-1 text-xs text-muted-foreground">
            UI preview only. No database or agent API connection.
          </p>
        </div>
      </SidebarFooter>
    </Sidebar>
  )
}
