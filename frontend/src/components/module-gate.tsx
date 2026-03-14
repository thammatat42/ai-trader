"use client";

import { Crown, Lock } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/auth-store";
import { usePlanStore } from "@/stores/plan-store";

interface ModuleGateProps {
  module: string;
  children: React.ReactNode;
}

export function ModuleGate({ module, children }: ModuleGateProps) {
  const user = useAuthStore((s) => s.user);
  const summary = usePlanStore((s) => s.summary);

  // Admin bypasses all checks
  if (user?.role === "admin") return <>{children}</>;

  // While loading plan data, show children (sidebar already filters nav)
  if (!summary) return <>{children}</>;

  if (summary.modules.includes(module)) return <>{children}</>;

  return (
    <div className="flex flex-col items-center justify-center gap-6 py-20 text-center">
      <div className="rounded-full bg-muted p-4">
        <Lock className="h-8 w-8 text-muted-foreground" />
      </div>
      <div>
        <h2 className="text-xl font-semibold">Module Locked</h2>
        <p className="mt-1 max-w-md text-sm text-muted-foreground">
          Your current plan does not include access to this feature.
          Upgrade your plan to unlock it.
        </p>
      </div>
      <Link href="/dashboard/plans">
        <Button>
          <Crown className="mr-2 h-4 w-4" />
          View Plans
        </Button>
      </Link>
    </div>
  );
}
