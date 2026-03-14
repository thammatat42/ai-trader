"use client";

import { useEffect, useState, useCallback } from "react";
import {
  ArrowUpRight,
  ArrowDownRight,
  RefreshCw,
  X,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/lib/api-client";
import type { Trade } from "@/types/api";

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

interface PositionsPanelProps {
  /** Auto-refresh interval in seconds. 0 to disable. */
  refreshInterval?: number;
}

export function PositionsPanel({ refreshInterval = 30 }: PositionsPanelProps) {
  const [positions, setPositions] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const fetchPositions = useCallback(async () => {
    try {
      const res = await apiClient.get("/api/v1/trades/positions");
      setPositions(res.data);
      setLastRefresh(new Date());
    } catch {
      // silently handle
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPositions();
    if (refreshInterval > 0) {
      const interval = setInterval(fetchPositions, refreshInterval * 1000);
      return () => clearInterval(interval);
    }
  }, [fetchPositions, refreshInterval]);

  const totalProfit = positions.reduce((sum, p) => sum + (p.profit ?? 0), 0);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <div>
          <CardTitle className="text-lg">Open Positions</CardTitle>
          {lastRefresh && (
            <p className="text-xs text-muted-foreground">
              Updated {lastRefresh.toLocaleTimeString()}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {positions.length > 0 && (
            <span
              className={`text-sm font-semibold ${
                totalProfit >= 0 ? "text-green-500" : "text-red-500"
              }`}
            >
              {formatCurrency(totalProfit)}
            </span>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={fetchPositions}
            disabled={loading}
          >
            <RefreshCw
              className={`h-4 w-4 ${loading ? "animate-spin" : ""}`}
            />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {loading && positions.length === 0 ? (
          <p className="text-sm text-muted-foreground">Loading positions...</p>
        ) : positions.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No open positions right now.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="px-3 py-2">Symbol</th>
                  <th className="px-3 py-2">Action</th>
                  <th className="px-3 py-2">Lot</th>
                  <th className="px-3 py-2">Open Price</th>
                  <th className="px-3 py-2">SL</th>
                  <th className="px-3 py-2">TP</th>
                  <th className="px-3 py-2">Profit</th>
                  <th className="px-3 py-2">Opened</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.id} className="border-b hover:bg-muted/50">
                    <td className="px-3 py-2 font-medium">{p.symbol}</td>
                    <td className="px-3 py-2">
                      <span className="inline-flex items-center gap-1">
                        {p.action === "BUY" ? (
                          <ArrowUpRight className="h-3.5 w-3.5 text-green-500" />
                        ) : (
                          <ArrowDownRight className="h-3.5 w-3.5 text-red-500" />
                        )}
                        {p.action}
                      </span>
                    </td>
                    <td className="px-3 py-2">{p.lot}</td>
                    <td className="px-3 py-2">
                      {p.open_price?.toFixed(2) ?? "—"}
                    </td>
                    <td className="px-3 py-2">
                      {p.sl_price?.toFixed(2) ?? "—"}
                    </td>
                    <td className="px-3 py-2">
                      {p.tp_price?.toFixed(2) ?? "—"}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`font-semibold ${
                          (p.profit ?? 0) >= 0
                            ? "text-green-500"
                            : "text-red-500"
                        }`}
                      >
                        {formatCurrency(p.profit ?? 0)}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-muted-foreground whitespace-nowrap">
                      {formatTime(p.opened_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
