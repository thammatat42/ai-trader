"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Crown,
  Check,
  Sparkles,
  ArrowRight,
  Clock,
  Loader2,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { apiClient } from "@/lib/api-client";
import { usePlanStore } from "@/stores/plan-store";
import { useAuthStore } from "@/stores/auth-store";
import type {
  Plan,
  PlanDetail,
  CreditBalance,
  CreditTransaction,
  Subscription,
  UserPlanSummary,
} from "@/types/api";

const planColors: Record<string, string> = {
  free: "border-zinc-500/30",
  starter: "border-blue-500/30",
  pro: "border-purple-500/50 ring-1 ring-purple-500/20",
  enterprise: "border-amber-500/50 ring-1 ring-amber-500/20",
};

const planAccentText: Record<string, string> = {
  free: "text-zinc-400",
  starter: "text-blue-400",
  pro: "text-purple-400",
  enterprise: "text-amber-400",
};

export default function PlansPage() {
  const queryClient = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const summary = usePlanStore((s) => s.summary);
  const setSummary = usePlanStore((s) => s.setSummary);
  const [selectedPlan, setSelectedPlan] = useState<string | null>(null);

  const { data: plans = [], isLoading: plansLoading } = useQuery<Plan[]>({
    queryKey: ["plans"],
    queryFn: () => apiClient.get("/api/v1/plans").then((r) => r.data),
  });

  const { data: planDetails } = useQuery<PlanDetail>({
    queryKey: ["plan-detail", selectedPlan],
    queryFn: () =>
      apiClient.get(`/api/v1/plans/${selectedPlan}`).then((r) => r.data),
    enabled: !!selectedPlan,
  });

  const { data: credits } = useQuery<CreditBalance>({
    queryKey: ["credits"],
    queryFn: () => apiClient.get("/api/v1/credits/me").then((r) => r.data),
  });

  const { data: transactions = [] } = useQuery<CreditTransaction[]>({
    queryKey: ["credit-transactions"],
    queryFn: () =>
      apiClient
        .get("/api/v1/credits/me/transactions?limit=20")
        .then((r) => r.data),
  });

  const { data: subscription } = useQuery<Subscription | null>({
    queryKey: ["subscription"],
    queryFn: () =>
      apiClient.get("/api/v1/subscriptions/me").then((r) => r.data),
  });

  const subscribeMutation = useMutation({
    mutationFn: (planCode: string) =>
      apiClient
        .post("/api/v1/subscriptions/subscribe", {
          plan_code: planCode,
          billing_cycle: "monthly",
        })
        .then((r) => r.data),
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ["subscription"] });
      queryClient.invalidateQueries({ queryKey: ["credits"] });
      queryClient.invalidateQueries({ queryKey: ["credit-transactions"] });
      // Refresh the plan summary in the store
      try {
        const res = await apiClient.get("/api/v1/subscriptions/me/summary");
        setSummary(res.data as UserPlanSummary);
      } catch {
        /* noop */
      }
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () =>
      apiClient.post("/api/v1/subscriptions/cancel").then((r) => r.data),
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ["subscription"] });
      try {
        const res = await apiClient.get("/api/v1/subscriptions/me/summary");
        setSummary(res.data as UserPlanSummary);
      } catch {
        /* noop */
      }
    },
  });

  const isAdmin = user?.role === "admin";
  const currentPlanCode = summary?.plan_code;

  if (plansLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold">Plans & Billing</h1>
        <p className="mt-1 text-muted-foreground">
          Manage your subscription and AI credits
        </p>
      </div>

      {/* Current Plan Summary */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Current Plan</CardDescription>
            <CardTitle className="flex items-center gap-2">
              <Crown className="h-5 w-5 text-yellow-500" />
              {summary?.plan_name ?? "No Plan"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {subscription && (
              <p className="text-xs text-muted-foreground">
                {subscription.billing_cycle} &middot;{" "}
                {subscription.status === "active" ? "Active" : subscription.status}
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardDescription>AI Credits</CardDescription>
            <CardTitle className="flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-yellow-500" />
              {credits?.balance ?? summary?.credits_balance ?? 0}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-muted-foreground">
              Lifetime: {credits?.lifetime_earned ?? 0} earned &middot;{" "}
              {credits?.lifetime_used ?? 0} used
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Accessible Modules</CardDescription>
            <CardTitle>{summary?.modules.length ?? 0}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-muted-foreground">
              {isAdmin ? "Admin — all modules" : "Based on your plan"}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Plan Cards */}
      <div>
        <h2 className="mb-4 text-xl font-semibold">Available Plans</h2>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {plans.map((plan) => {
            const isCurrent = currentPlanCode === plan.code;
            const colorClass = planColors[plan.code] ?? "border-border";
            const accentClass = planAccentText[plan.code] ?? "text-foreground";

            return (
              <Card
                key={plan.id}
                className={`relative flex flex-col ${colorClass} ${
                  isCurrent ? "bg-accent/30" : ""
                }`}
              >
                {isCurrent && (
                  <div className="absolute -top-3 left-4">
                    <Badge className="bg-primary text-primary-foreground">
                      Current
                    </Badge>
                  </div>
                )}
                <CardHeader className="flex-1">
                  <CardTitle className={`flex items-center gap-2 ${accentClass}`}>
                    {plan.name}
                  </CardTitle>
                  <CardDescription className="min-h-[2.5rem]">
                    {plan.description}
                  </CardDescription>
                  <div className="mt-2">
                    {plan.price_monthly === 0 ? (
                      <span className="text-3xl font-bold">Free</span>
                    ) : (
                      <div>
                        <span className="text-3xl font-bold">
                          ${plan.price_monthly}
                        </span>
                        <span className="text-sm text-muted-foreground">
                          /month
                        </span>
                      </div>
                    )}
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  <ul className="space-y-2 text-sm">
                    <li className="flex items-center gap-2">
                      <Check className="h-4 w-4 text-green-500" />
                      {plan.ai_credits_monthly.toLocaleString()} AI credits/month
                    </li>
                    <li className="flex items-center gap-2">
                      <Check className="h-4 w-4 text-green-500" />
                      {plan.max_platforms} platform
                      {plan.max_platforms !== 1 ? "s" : ""}
                    </li>
                    <li className="flex items-center gap-2">
                      <Check className="h-4 w-4 text-green-500" />
                      {plan.max_trades_per_day >= 9999
                        ? "Unlimited"
                        : plan.max_trades_per_day}{" "}
                      trades/day
                    </li>
                    <li className="flex items-center gap-2">
                      <Check className="h-4 w-4 text-green-500" />
                      {plan.max_api_keys >= 9999
                        ? "Unlimited"
                        : plan.max_api_keys}{" "}
                      API key{plan.max_api_keys !== 1 ? "s" : ""}
                    </li>
                  </ul>

                  <Button
                    className="w-full"
                    variant={isCurrent ? "outline" : "default"}
                    disabled={
                      isCurrent ||
                      isAdmin ||
                      subscribeMutation.isPending
                    }
                    onClick={() => {
                      setSelectedPlan(plan.code);
                      subscribeMutation.mutate(plan.code);
                    }}
                  >
                    {subscribeMutation.isPending &&
                    selectedPlan === plan.code ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : isCurrent ? (
                      "Current Plan"
                    ) : (
                      <>
                        {currentPlanCode &&
                        plans.findIndex((p) => p.code === plan.code) >
                          plans.findIndex(
                            (p) => p.code === currentPlanCode
                          )
                          ? "Upgrade"
                          : "Switch"}
                        <ArrowRight className="ml-2 h-4 w-4" />
                      </>
                    )}
                  </Button>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>

      {/* Plan modules detail */}
      {selectedPlan && planDetails && (
        <Card>
          <CardHeader>
            <CardTitle>{planDetails.name} — Included Modules</CardTitle>
            <CardDescription>
              {planDetails.modules.length} modules included
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {planDetails.modules.map((pm) => (
                <div
                  key={pm.module.id}
                  className="flex items-center gap-3 rounded-md border border-border p-3 text-sm"
                >
                  <Check className="h-4 w-4 shrink-0 text-green-500" />
                  <div>
                    <span className="font-medium">{pm.module.name}</span>
                    {pm.access_level !== "full" && (
                      <Badge variant="secondary" className="ml-2 text-xs">
                        {pm.access_level}
                      </Badge>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Cancel subscription */}
      {subscription && subscription.status === "active" && !isAdmin && (
        <Card className="border-red-500/30">
          <CardHeader>
            <CardTitle className="text-red-400">Cancel Subscription</CardTitle>
            <CardDescription>
              Cancelling reverts you to the free tier. Your credits will remain.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              variant="outline"
              className="border-red-500/30 text-red-400 hover:bg-red-500/10"
              onClick={() => cancelMutation.mutate()}
              disabled={cancelMutation.isPending}
            >
              {cancelMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : null}
              Cancel Subscription
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Credit Transaction History */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Clock className="h-5 w-5" />
            Credit History
          </CardTitle>
          <CardDescription>Recent credit transactions</CardDescription>
        </CardHeader>
        <CardContent>
          {transactions.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              No credit transactions yet.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-muted-foreground">
                    <th className="pb-2 pr-4">Date</th>
                    <th className="pb-2 pr-4">Type</th>
                    <th className="pb-2 pr-4">Amount</th>
                    <th className="pb-2 pr-4">Balance</th>
                    <th className="pb-2">Description</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {transactions.map((tx) => (
                    <tr key={tx.id}>
                      <td className="py-2 pr-4 whitespace-nowrap text-muted-foreground">
                        {new Date(tx.created_at).toLocaleDateString()}
                      </td>
                      <td className="py-2 pr-4">
                        <Badge variant="secondary" className="text-xs">
                          {tx.tx_type.replace(/_/g, " ")}
                        </Badge>
                      </td>
                      <td
                        className={`py-2 pr-4 font-medium ${
                          tx.amount >= 0 ? "text-green-400" : "text-red-400"
                        }`}
                      >
                        {tx.amount >= 0 ? "+" : ""}
                        {tx.amount}
                      </td>
                      <td className="py-2 pr-4">{tx.balance_after}</td>
                      <td className="py-2 text-muted-foreground">
                        {tx.description ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
