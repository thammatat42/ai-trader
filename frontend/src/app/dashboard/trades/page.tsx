"use client";

import { useEffect, useState, useCallback } from "react";
import {
  ArrowUpRight,
  ArrowDownRight,
  Download,
  ChevronLeft,
  ChevronRight,
  Search,
  Filter,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ModuleGate } from "@/components/module-gate";
import { apiClient } from "@/lib/api-client";
import { useAuth } from "@/hooks/use-auth";
import type { Trade, TradingPlatform } from "@/types/api";

function formatCurrency(n: number) {
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  });
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function TradesPage() {
  useAuth();
  const [trades, setTrades] = useState<Trade[]>([]);
  const [platforms, setPlatforms] = useState<TradingPlatform[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(0);
  const [perPage] = useState(20);
  const [statusFilter, setStatusFilter] = useState<string>("ALL");
  const [symbolFilter, setSymbolFilter] = useState("");
  const [platformFilter, setPlatformFilter] = useState("");
  const [loading, setLoading] = useState(true);

  const fetchTrades = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = { page, per_page: perPage };
      if (statusFilter !== "ALL") params.status = statusFilter;
      if (symbolFilter.trim()) params.symbol = symbolFilter.trim().toUpperCase();
      if (platformFilter) params.platform_id = platformFilter;

      const res = await apiClient.get("/api/v1/trades", { params });
      setTrades(res.data.items);
      setTotal(res.data.total);
      setPages(res.data.pages);
    } catch {
      // empty
    } finally {
      setLoading(false);
    }
  }, [page, perPage, statusFilter, symbolFilter, platformFilter]);

  useEffect(() => {
    fetchTrades();
  }, [fetchTrades]);

  useEffect(() => {
    apiClient.get("/api/v1/platforms").then((r) => setPlatforms(r.data)).catch(() => {});
  }, []);

  // Reset page when filters change
  useEffect(() => {
    setPage(1);
  }, [statusFilter, symbolFilter, platformFilter]);

  const getPlatformName = (id: string | null) => {
    if (!id) return "—";
    return platforms.find((p) => p.id === id)?.name ?? id.slice(0, 8);
  };

  // CSV export
  const exportCSV = () => {
    if (trades.length === 0) return;
    const headers = [
      "Symbol",
      "Action",
      "Lot",
      "Open Price",
      "Close Price",
      "SL",
      "TP",
      "Profit",
      "Commission",
      "Swap",
      "Status",
      "Opened At",
      "Closed At",
      "Platform",
      "Order ID",
    ];
    const rows = trades.map((t) => [
      t.symbol,
      t.action,
      t.lot,
      t.open_price ?? "",
      t.close_price ?? "",
      t.sl_price ?? "",
      t.tp_price ?? "",
      t.profit ?? "",
      t.commission ?? "",
      t.swap ?? "",
      t.status,
      t.opened_at,
      t.closed_at ?? "",
      getPlatformName(t.platform_id),
      t.order_id ?? "",
    ]);

    const csv = [headers, ...rows].map((r) => r.join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `trades-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <ModuleGate module="trades">
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-3xl font-bold">Trades</h1>
          <Button
            variant="outline"
            size="sm"
            onClick={exportCSV}
            disabled={trades.length === 0}
          >
            <Download className="mr-2 h-4 w-4" />
            Export CSV
          </Button>
        </div>

        {/* ── Filters ── */}
        <Card>
          <CardContent className="flex flex-wrap items-center gap-3 pt-4 pb-4">
            <Filter className="h-4 w-4 text-muted-foreground" />

            {/* Status filter */}
            <div className="flex gap-1">
              {["ALL", "OPEN", "CLOSED"].map((s) => (
                <Button
                  key={s}
                  size="sm"
                  variant={statusFilter === s ? "default" : "outline"}
                  onClick={() => setStatusFilter(s)}
                >
                  {s}
                </Button>
              ))}
            </div>

            {/* Symbol search */}
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Symbol"
                value={symbolFilter}
                onChange={(e) => setSymbolFilter(e.target.value)}
                className="w-32 pl-8"
              />
            </div>

            {/* Platform filter */}
            {platforms.length > 0 && (
              <select
                className="rounded-md border bg-background px-3 py-2 text-sm"
                value={platformFilter}
                onChange={(e) => setPlatformFilter(e.target.value)}
              >
                <option value="">All Platforms</option>
                {platforms.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            )}

            <span className="ml-auto text-sm text-muted-foreground">
              {total} trade{total !== 1 ? "s" : ""}
            </span>
          </CardContent>
        </Card>

        {/* ── Trade Table ── */}
        <Card>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="px-4 py-3">Symbol</th>
                    <th className="px-4 py-3">Action</th>
                    <th className="px-4 py-3">Lot</th>
                    <th className="px-4 py-3">Open</th>
                    <th className="px-4 py-3">Close</th>
                    <th className="px-4 py-3">SL</th>
                    <th className="px-4 py-3">TP</th>
                    <th className="px-4 py-3">Profit</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Platform</th>
                    <th className="px-4 py-3">Opened</th>
                  </tr>
                </thead>
                <tbody>
                  {loading ? (
                    <tr>
                      <td colSpan={11} className="px-4 py-8 text-center text-muted-foreground">
                        Loading...
                      </td>
                    </tr>
                  ) : trades.length === 0 ? (
                    <tr>
                      <td colSpan={11} className="px-4 py-8 text-center text-muted-foreground">
                        No trades found.
                      </td>
                    </tr>
                  ) : (
                    trades.map((t) => (
                      <tr key={t.id} className="border-b hover:bg-muted/50">
                        <td className="px-4 py-3 font-medium">{t.symbol}</td>
                        <td className="px-4 py-3">
                          <span className="inline-flex items-center gap-1">
                            {t.action === "BUY" ? (
                              <ArrowUpRight className="h-3.5 w-3.5 text-green-500" />
                            ) : (
                              <ArrowDownRight className="h-3.5 w-3.5 text-red-500" />
                            )}
                            {t.action}
                          </span>
                        </td>
                        <td className="px-4 py-3">{t.lot}</td>
                        <td className="px-4 py-3">
                          {t.open_price?.toFixed(2) ?? "—"}
                        </td>
                        <td className="px-4 py-3">
                          {t.close_price?.toFixed(2) ?? "—"}
                        </td>
                        <td className="px-4 py-3">
                          {t.sl_price?.toFixed(2) ?? "—"}
                        </td>
                        <td className="px-4 py-3">
                          {t.tp_price?.toFixed(2) ?? "—"}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`font-semibold ${
                              (t.profit ?? 0) >= 0 ? "text-green-500" : "text-red-500"
                            }`}
                          >
                            {t.profit != null ? formatCurrency(t.profit) : "—"}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <Badge
                            variant={t.status === "OPEN" ? "success" : "secondary"}
                          >
                            {t.status}
                          </Badge>
                        </td>
                        <td className="px-4 py-3 text-muted-foreground">
                          {getPlatformName(t.platform_id)}
                        </td>
                        <td className="px-4 py-3 text-muted-foreground whitespace-nowrap">
                          {formatDate(t.opened_at)}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {pages > 1 && (
              <div className="flex items-center justify-between border-t px-4 py-3">
                <span className="text-sm text-muted-foreground">
                  Page {page} of {pages}
                </span>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page <= 1}
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage((p) => Math.min(pages, p + 1))}
                    disabled={page >= pages}
                  >
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </ModuleGate>
  );
}
