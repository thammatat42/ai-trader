"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  ArrowLeftRight,
  BarChart3,
  Brain,
  Server,
  Bot,
  Key,
  ScrollText,
  Settings,
  ChevronLeft,
  Users,
  Crown,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useState } from "react";
import { useAuthStore } from "@/stores/auth-store";
import { usePlanStore } from "@/stores/plan-store";

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard, module: "dashboard" },
  { href: "/dashboard/trades", label: "Trades", icon: ArrowLeftRight, module: "trades" },
  { href: "/dashboard/analytics", label: "Analytics", icon: BarChart3, module: "analytics" },
  { href: "/dashboard/ai-providers", label: "AI Providers", icon: Brain, module: "ai_providers" },
  { href: "/dashboard/platforms", label: "Platforms", icon: Server, module: "platforms" },
  { href: "/dashboard/bot-control", label: "Bot Control", icon: Bot, module: "bot_control" },
  { href: "/dashboard/api-keys", label: "API Keys", icon: Key, module: "api_keys" },
  { href: "/dashboard/logs", label: "Logs", icon: ScrollText, module: "logs" },
  { href: "/dashboard/users", label: "Users", icon: Users, module: "user_management" },
  { href: "/dashboard/settings", label: "Settings", icon: Settings, module: "settings" },
  { href: "/dashboard/plans", label: "Plans & Billing", icon: Crown, module: null },
];

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const user = useAuthStore((s) => s.user);
  const summary = usePlanStore((s) => s.summary);

  const visibleItems = navItems.filter((item) => {
    if (!item.module) return true;
    if (user?.role === "admin") return true;
    if (!summary) return item.module === "dashboard" || item.module === "settings";
    return summary.modules.includes(item.module);
  });

  return (
    <aside
      className={cn(
        "flex flex-col border-r border-border bg-card transition-all duration-300",
        collapsed ? "w-16" : "w-64"
      )}
    >
      <div className="flex h-14 items-center justify-between border-b border-border px-4">
        {!collapsed && (
          <Link href="/dashboard" className="text-lg font-bold text-primary">
            AI Trader
          </Link>
        )}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="rounded-md p-1.5 hover:bg-accent"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <ChevronLeft
            className={cn(
              "h-4 w-4 transition-transform",
              collapsed && "rotate-180"
            )}
          />
        </button>
      </div>

      <nav className="flex-1 space-y-1 p-2">
        {visibleItems.map((item) => {
          const isActive =
            pathname === item.href ||
            (item.href !== "/dashboard" && pathname.startsWith(item.href));
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                isActive
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              )}
              title={collapsed ? item.label : undefined}
            >
              <item.icon className="h-4 w-4 shrink-0" />
              {!collapsed && <span>{item.label}</span>}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
