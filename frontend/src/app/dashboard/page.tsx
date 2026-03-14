"use client";

import { useEffect, useState } from "react";
import {
  DollarSign,
  TrendingUp,
  TrendingDown,
  Activity,
  BarChart3,
  ArrowUpRight,
  ArrowDownRight,
  Clock,
} from "lucide-react";
import { StatCard } from "@/components/ui/stat-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { apiClient } from "@/lib/api-client";
import { useAuth } from "@/hooks/use-auth";
import type { Trade, TradeSummary, TradingPlatform } from "@/types/api";

function formatCurrency(n: number) {
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  });
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function DashboardPage() {
  useAuth();
  const [summary, setSummary] = useState<TradeSummary | null>(null);
  const [positions, setPositions] = useState<Trade[]>([]);
  const [recentTrades, setRecentTrades] = useState<Trade[]>([]);
  const [platforms, setPlatforms] = useState<TradingPlatform[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [summaryRes, positionsRes, tradesRes, platformsRes] =
          await Promise.all([
            apiClient.get("/api/v1/trades/summary"),
            apiClient.get("/api/v1/trades/positions"),
            apiClient.get("/api/v1/trades?per_page=5"),
            apiClient.get("/api/v1/platforms"),
          ]);
        setSummary(summaryRes.data);
        setPositions(positionsRes.data);
        setRecentTrades(tradesRes.data.items ?? []);
        setPlatforms(platformsRes.data);
      } catch {
        // silently handle — user sees empty state
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const activePlatforms = platforms.filter((p) => p.is_active);
  const todayPnl = summary?.today_profit ?? 0;
  const todayPositive = todayPnl >= 0;

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Dashboard</h1>

      {/* ── Stat Cards ── */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title="Total P&L"
          value={formatCurrency(summary?.total_profit ?? 0)}
          icon={DollarSign}
          description={`${summary?.closed_trades ?? 0} closed trades`}
        />
        <StatCard
          title="Today's P&L"
          value={formatCurrency(todayPnl)}
          icon={todayPositive ? TrendingUp : TrendingDown}
          trend={
            summary?.closed_trades
              ? { value: Math.abs(todayPnl), isPositive: todayPositive }
              : undefined
          }
        />
        <StatCard
          title="Open Positions"
          value={String(summary?.open_trades ?? 0)}
          icon={Activity}
          description={`${activePlatforms.length} active platform${activePlatforms.length !== 1 ? "s" : ""}`}
        />
        <StatCard
          title="Win Rate"
          value={`${summary?.win_rate ?? 0}%`}
          icon={BarChart3}
          description={`Best: ${formatCurrency(summary?.best_trade ?? 0)}`}
        />
      </div>

      {/* ── Two-column: Positions + Recent Trades ── */}
      <div className="grid gap-4 md:grid-cols-2">
        {/* Open Positions */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-lg">Open Positions</CardTitle>
            <Badge variant="secondary">{positions.length}</Badge>
          </CardHeader>
          <CardContent>
            {loading ? (
              <p className="text-sm text-muted-foreground">Loading...</p>
            ) : positions.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No open positions.
              </p>
            ) : (
              <div className="space-y-3">
                {positions.slice(0, 5).map((p) => (
                  <div
                    key={p.id}
                    className="flex items-center justify-between rounded-lg border p-3"
                  >
                    <div className="flex items-center gap-3">
                      <div
                        className={`flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold ${
                          p.action === "BUY"
                            ? "bg-green-500/20 text-green-500"
                            : "bg-red-500/20 text-red-500"
                        }`}
                      >
                        {p.action === "BUY" ? (
                          <ArrowUpRight className="h-4 w-4" />
                        ) : (
                          <ArrowDownRight className="h-4 w-4" />
                        )}
                      </div>
                      <div>
                        <p className="text-sm font-medium">
                          {p.symbol}{" "}
                          <span className="text-muted-foreground">
                            {p.lot} lot
                          </span>
                        </p>
                        <p className="text-xs text-muted-foreground">
                          Open: {p.open_price?.toFixed(2) ?? "—"}
                        </p>
                      </div>
                    </div>
                    <div className="text-right">
                      <p
                        className={`text-sm font-semibold ${
                          (p.profit ?? 0) >= 0
                            ? "text-green-500"
                            : "text-red-500"
                        }`}
                      >
                        {formatCurrency(p.profit ?? 0)}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Recent Trades */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-lg">Recent Trades</CardTitle>
          </CardHeader>
          <CardContent>
            {loading ? (
              <p className="text-sm text-muted-foreground">Loading...</p>
            ) : recentTrades.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No trades yet. Connect a platform to start trading.
              </p>
            ) : (
              <div className="space-y-3">
                {recentTrades.map((t) => (
                  <div
                    key={t.id}
                    className="flex items-center justify-between rounded-lg border p-3"
                  >
                    <div className="flex items-center gap-3">
                      <div
                        className={`flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold ${
                          t.action === "BUY"
                            ? "bg-green-500/20 text-green-500"
                            : "bg-red-500/20 text-red-500"
                        }`}
                      >
                        {t.action === "BUY" ? (
                          <ArrowUpRight className="h-4 w-4" />
                        ) : (
                          <ArrowDownRight className="h-4 w-4" />
                        )}
                      </div>
                      <div>
                        <p className="text-sm font-medium">
                          {t.symbol}{" "}
                          <Badge
                            variant={
                              t.status === "OPEN" ? "success" : "secondary"
                            }
                            className="ml-1"
                          >
                            {t.status}
                          </Badge>
                        </p>
                        <p className="flex items-center gap-1 text-xs text-muted-foreground">
                          <Clock className="h-3 w-3" />
                          {formatTime(t.opened_at)}
                        </p>
                      </div>
                    </div>
                    <div className="text-right">
                      <p
                        className={`text-sm font-semibold ${
                          (t.profit ?? 0) >= 0
                            ? "text-green-500"
                            : "text-red-500"
                        }`}
                      >
                        {t.profit != null ? formatCurrency(t.profit) : "—"}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {t.lot} lot
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ── Platform Status ── */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Connected Platforms</CardTitle>
        </CardHeader>
        <CardContent>
          {platforms.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No platforms configured. Go to Platforms to add one.
            </p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {platforms.map((pl) => (
                <div
                  key={pl.id}
                  className="flex items-center justify-between rounded-lg border p-4"
                >
                  <div>
                    <p className="font-medium">{pl.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {pl.platform_type.toUpperCase()} · {pl.market_hours}
                    </p>
                  </div>
                  <Badge variant={pl.is_active ? "success" : "secondary"}>
                    {pl.is_active ? "Active" : "Inactive"}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
