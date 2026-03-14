"use client";

import { Moon, Sun, Bell, LogOut, Sparkles } from "lucide-react";
import { useTheme } from "next-themes";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/stores/auth-store";
import { usePlanStore } from "@/stores/plan-store";
import { apiClient } from "@/lib/api-client";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";

export function Header() {
  const { theme, setTheme } = useTheme();
  const router = useRouter();
  const { user, logout: storeLogout } = useAuthStore();
  const summary = usePlanStore((s) => s.summary);
  const clearPlan = usePlanStore((s) => s.clear);

  async function handleLogout() {
    try {
      await apiClient.post("/api/v1/auth/logout");
    } catch {
      // Logout even if the API call fails
    }
    storeLogout();
    clearPlan();
    router.push("/login");
  }

  return (
    <header className="flex h-14 items-center justify-between border-b border-border bg-card px-6">
      <div />

      <div className="flex items-center gap-3">
        {/* Credit balance */}
        {summary && summary.plan_code !== "admin" && (
          <Link
            href="/dashboard/plans"
            className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs hover:bg-accent transition-colors"
          >
            <Sparkles className="h-3.5 w-3.5 text-yellow-500" />
            <span className="font-medium">{summary.credits_balance}</span>
            <span className="text-muted-foreground">credits</span>
          </Link>
        )}

        {/* Plan badge */}
        {summary && (
          <Badge
            variant={summary.plan_code === "admin" ? "default" : "secondary"}
            className="text-xs"
          >
            {summary.plan_name ?? "No Plan"}
          </Badge>
        )}

        <button
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          className="rounded-md p-2 hover:bg-accent"
          aria-label="Toggle theme"
        >
          <Sun className="h-4 w-4 rotate-0 scale-100 transition-transform dark:-rotate-90 dark:scale-0" />
          <Moon className="absolute h-4 w-4 rotate-90 scale-0 transition-transform dark:rotate-0 dark:scale-100" />
        </button>

        <button
          className="relative rounded-md p-2 hover:bg-accent"
          aria-label="Notifications"
        >
          <Bell className="h-4 w-4" />
        </button>

        {user && (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">{user.email}</span>
            <Badge variant="secondary" className="text-xs">{user.role}</Badge>
          </div>
        )}

        <button
          onClick={handleLogout}
          className="flex items-center gap-1 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-foreground"
          aria-label="Logout"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </div>
    </header>
  );
}
