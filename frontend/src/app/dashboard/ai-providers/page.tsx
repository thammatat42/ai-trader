"use client";

import { useEffect, useState } from "react";
import {
  Brain,
  Plus,
  FlaskConical,
  Power,
  Pencil,
  Trash2,
  Activity,
  Clock,
  Zap,
  Loader2,
  CheckCircle2,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import {
  Dialog,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { ModuleGate } from "@/components/module-gate";
import { apiClient } from "@/lib/api-client";
import { useAuth } from "@/hooks/use-auth";
import type {
  AiProvider,
  AiProviderCreateRequest,
  AiProviderUpdateRequest,
  AiProviderTestResponse,
  AiAnalysisLog,
  TradingPlatform,
} from "@/types/api";

// ---------------------------------------------------------------------------
//  Main page
// ---------------------------------------------------------------------------
export default function AiProvidersPage() {
  useAuth();
  const [providers, setProviders] = useState<AiProvider[]>([]);
  const [providerTypes, setProviderTypes] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  // Dialogs
  const [showAdd, setShowAdd] = useState(false);
  const [editProvider, setEditProvider] = useState<AiProvider | null>(null);
  const [deleteProvider, setDeleteProvider] = useState<AiProvider | null>(null);
  const [testResult, setTestResult] = useState<{
    provider: AiProvider;
    result: AiProviderTestResponse | null;
    testing: boolean;
  } | null>(null);

  // Analysis viewer (story 3.9)
  const [analysisLogs, setAnalysisLogs] = useState<AiAnalysisLog[]>([]);
  const [showLogs, setShowLogs] = useState(false);

  const load = async () => {
    try {
      const [provRes, typesRes] = await Promise.all([
        apiClient.get("/api/v1/ai-providers"),
        apiClient.get("/api/v1/ai-providers/types"),
      ]);
      setProviders(provRes.data);
      setProviderTypes(typesRes.data);
    } catch {
      /* empty */
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleActivate = async (p: AiProvider) => {
    await apiClient.put(`/api/v1/ai-providers/${p.id}/activate`);
    await load();
  };

  const handleDelete = async () => {
    if (!deleteProvider) return;
    await apiClient.delete(`/api/v1/ai-providers/${deleteProvider.id}`);
    setDeleteProvider(null);
    await load();
  };

  const handleTest = async (p: AiProvider) => {
    setTestResult({ provider: p, result: null, testing: true });
    try {
      const res = await apiClient.post(`/api/v1/ai-providers/${p.id}/test`);
      setTestResult({ provider: p, result: res.data, testing: false });
    } catch {
      setTestResult({
        provider: p,
        result: { is_healthy: false, latency_ms: 0, message: "Request failed" },
        testing: false,
      });
    }
    await load(); // refresh latency stats
  };

  const handleShowLogs = async () => {
    try {
      const res = await apiClient.get("/api/v1/ai-providers/analysis-logs?per_page=50");
      setAnalysisLogs(res.data);
    } catch {
      /* empty */
    }
    setShowLogs(true);
  };

  const active = providers.find((p) => p.is_active);

  return (
    <ModuleGate module="ai_providers">
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <h1 className="text-3xl font-bold">AI Providers</h1>
          <div className="flex gap-2">
            <Button variant="outline" onClick={handleShowLogs}>
              <Activity className="mr-2 h-4 w-4" />
              Analysis Logs
            </Button>
            <Button onClick={() => setShowAdd(true)}>
              <Plus className="mr-2 h-4 w-4" />
              Add Provider
            </Button>
          </div>
        </div>

        {/* Active Provider Banner */}
        {active && (
          <Card className="border-green-500/30 bg-green-500/5">
            <CardContent className="flex items-center justify-between py-4">
              <div className="flex items-center gap-3">
                <Zap className="h-5 w-5 text-green-500" />
                <div>
                  <p className="text-sm font-semibold">Active Provider</p>
                  <p className="text-xs text-muted-foreground">
                    {active.name} — {active.model}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-4 text-sm text-muted-foreground">
                {active.avg_latency_ms != null && (
                  <span className="flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {active.avg_latency_ms}ms avg
                  </span>
                )}
                <Badge variant="success">Active</Badge>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Provider Cards */}
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading providers...</p>
        ) : providers.length === 0 ? (
          <Card>
            <CardContent className="py-12 text-center">
              <Brain className="mx-auto mb-4 h-12 w-12 text-muted-foreground" />
              <p className="text-lg font-semibold">No AI Providers</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Add an AI provider to enable market analysis.
              </p>
              <Button className="mt-4" onClick={() => setShowAdd(true)}>
                <Plus className="mr-2 h-4 w-4" />
                Add Provider
              </Button>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {providers.map((p) => (
              <ProviderCard
                key={p.id}
                provider={p}
                onEdit={() => setEditProvider(p)}
                onDelete={() => setDeleteProvider(p)}
                onTest={() => handleTest(p)}
                onActivate={() => handleActivate(p)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Add Dialog */}
      <ProviderFormDialog
        open={showAdd}
        onOpenChange={setShowAdd}
        providerTypes={providerTypes}
        onSaved={() => {
          setShowAdd(false);
          load();
        }}
      />

      {/* Edit Dialog */}
      <ProviderFormDialog
        open={!!editProvider}
        onOpenChange={(o) => !o && setEditProvider(null)}
        providerTypes={providerTypes}
        provider={editProvider ?? undefined}
        onSaved={() => {
          setEditProvider(null);
          load();
        }}
      />

      {/* Delete Confirm */}
      <Dialog open={!!deleteProvider} onOpenChange={(o) => !o && setDeleteProvider(null)}>
        <DialogHeader>
          <DialogTitle>Delete Provider</DialogTitle>
          <DialogDescription>
            Are you sure you want to delete &quot;{deleteProvider?.name}&quot;? This action cannot be undone.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => setDeleteProvider(null)}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={handleDelete}>
            Delete
          </Button>
        </DialogFooter>
      </Dialog>

      {/* Test Result */}
      <Dialog open={!!testResult} onOpenChange={(o) => !o && setTestResult(null)}>
        <DialogHeader>
          <DialogTitle>Connection Test</DialogTitle>
          <DialogDescription>
            Testing {testResult?.provider.name}...
          </DialogDescription>
        </DialogHeader>
        <div className="py-4">
          {testResult?.testing ? (
            <div className="flex items-center justify-center gap-2 py-8">
              <Loader2 className="h-5 w-5 animate-spin" />
              <span className="text-sm">Testing connection...</span>
            </div>
          ) : testResult?.result ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                {testResult.result.is_healthy ? (
                  <CheckCircle2 className="h-5 w-5 text-green-500" />
                ) : (
                  <XCircle className="h-5 w-5 text-red-500" />
                )}
                <span className="font-medium">
                  {testResult.result.is_healthy ? "Healthy" : "Unhealthy"}
                </span>
              </div>
              <div className="rounded-md bg-muted p-3 text-sm">
                <p>
                  <span className="text-muted-foreground">Latency:</span>{" "}
                  {testResult.result.latency_ms}ms
                </p>
                <p>
                  <span className="text-muted-foreground">Message:</span>{" "}
                  {testResult.result.message}
                </p>
              </div>
            </div>
          ) : null}
        </div>
        <DialogFooter>
          <Button onClick={() => setTestResult(null)}>Close</Button>
        </DialogFooter>
      </Dialog>

      {/* Analysis Logs (story 3.9) */}
      <Dialog open={showLogs} onOpenChange={setShowLogs}>
        <DialogHeader>
          <DialogTitle>AI Analysis Logs</DialogTitle>
          <DialogDescription>
            Recent AI analysis results with provider traceability.
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-96 overflow-y-auto">
          {analysisLogs.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              No analysis logs yet.
            </p>
          ) : (
            <div className="space-y-2">
              {analysisLogs.map((log) => (
                <div
                  key={log.id}
                  className="rounded-md border p-3 text-sm"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{log.symbol}</span>
                      <Badge
                        variant={
                          log.sentiment === "BULLISH"
                            ? "success"
                            : log.sentiment === "BEARISH"
                              ? "destructive"
                              : "secondary"
                        }
                      >
                        {log.sentiment ?? "—"}
                      </Badge>
                      <Badge variant="outline">{log.trade_action}</Badge>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {log.latency_ms}ms
                    </span>
                  </div>
                  {log.ai_recommendation && (
                    <p className="mt-1 text-xs text-muted-foreground line-clamp-2">
                      {log.ai_recommendation}
                    </p>
                  )}
                  <div className="mt-1 flex gap-3 text-xs text-muted-foreground">
                    <span>Bid: {log.bid?.toFixed(2) ?? "—"}</span>
                    <span>Ask: {log.ask?.toFixed(2) ?? "—"}</span>
                    <span>
                      {new Date(log.created_at).toLocaleString("en-US", {
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setShowLogs(false)}>
            Close
          </Button>
        </DialogFooter>
      </Dialog>
    </ModuleGate>
  );
}

// ---------------------------------------------------------------------------
//  Provider Card
// ---------------------------------------------------------------------------
function ProviderCard({
  provider: p,
  onEdit,
  onDelete,
  onTest,
  onActivate,
}: {
  provider: AiProvider;
  onEdit: () => void;
  onDelete: () => void;
  onTest: () => void;
  onActivate: () => void;
}) {
  return (
    <Card className={p.is_active ? "border-green-500/30" : ""}>
      <CardHeader className="flex flex-row items-start justify-between pb-2">
        <div className="space-y-1">
          <CardTitle className="text-base">{p.name}</CardTitle>
          <p className="text-xs text-muted-foreground">
            {p.provider_type} — {p.model}
          </p>
        </div>
        {p.is_active ? (
          <Badge variant="success">Active</Badge>
        ) : (
          <Badge variant="secondary">Inactive</Badge>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-2 text-sm">
          <div>
            <span className="text-muted-foreground">Max Tokens</span>
            <p className="font-medium">{p.max_tokens}</p>
          </div>
          <div>
            <span className="text-muted-foreground">Temperature</span>
            <p className="font-medium">{p.temperature}</p>
          </div>
          <div>
            <span className="text-muted-foreground">Avg Latency</span>
            <p className="font-medium">
              {p.avg_latency_ms != null ? `${p.avg_latency_ms}ms` : "—"}
            </p>
          </div>
          <div>
            <span className="text-muted-foreground">Last Check</span>
            <p className="font-medium">
              {p.last_health_at
                ? new Date(p.last_health_at).toLocaleString("en-US", {
                    month: "short",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  })
                : "Never"}
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={onTest}>
            <FlaskConical className="mr-1 h-3 w-3" />
            Test
          </Button>
          {!p.is_active && (
            <Button size="sm" variant="outline" onClick={onActivate}>
              <Power className="mr-1 h-3 w-3" />
              Activate
            </Button>
          )}
          <Button size="sm" variant="outline" onClick={onEdit}>
            <Pencil className="mr-1 h-3 w-3" />
            Edit
          </Button>
          {!p.is_active && (
            <Button size="sm" variant="outline" onClick={onDelete}>
              <Trash2 className="mr-1 h-3 w-3" />
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
//  Add / Edit form dialog
// ---------------------------------------------------------------------------
function ProviderFormDialog({
  open,
  onOpenChange,
  providerTypes,
  provider,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  providerTypes: string[];
  provider?: AiProvider;
  onSaved: () => void;
}) {
  const isEdit = !!provider;
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const [name, setName] = useState("");
  const [providerType, setProviderType] = useState("");
  const [endpointUrl, setEndpointUrl] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [maxTokens, setMaxTokens] = useState("100");
  const [temperature, setTemperature] = useState("0.1");

  // Fill form when editing
  useEffect(() => {
    if (provider) {
      setName(provider.name);
      setProviderType(provider.provider_type);
      setEndpointUrl(provider.endpoint_url);
      setModel(provider.model);
      setApiKey("");
      setMaxTokens(String(provider.max_tokens));
      setTemperature(String(provider.temperature));
    } else {
      setName("");
      setProviderType(providerTypes[0] ?? "");
      setEndpointUrl("");
      setModel("");
      setApiKey("");
      setMaxTokens("100");
      setTemperature("0.1");
    }
    setError("");
  }, [provider, open, providerTypes]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSaving(true);

    try {
      if (isEdit) {
        const body: AiProviderUpdateRequest = {};
        if (name !== provider!.name) body.name = name;
        if (endpointUrl !== provider!.endpoint_url) body.endpoint_url = endpointUrl;
        if (model !== provider!.model) body.model = model;
        if (apiKey) body.api_key = apiKey;
        if (Number(maxTokens) !== provider!.max_tokens) body.max_tokens = Number(maxTokens);
        if (Number(temperature) !== provider!.temperature) body.temperature = Number(temperature);

        await apiClient.put(`/api/v1/ai-providers/${provider!.id}`, body);
      } else {
        const body: AiProviderCreateRequest = {
          name,
          provider_type: providerType,
          endpoint_url: endpointUrl,
          model,
          api_key: apiKey,
          max_tokens: Number(maxTokens),
          temperature: Number(temperature),
        };
        await apiClient.post("/api/v1/ai-providers", body);
      }
      onSaved();
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Failed to save provider";
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  const defaultEndpoints: Record<string, string> = {
    openrouter: "https://openrouter.ai/api/v1/chat/completions",
    nvidia_nim: "https://integrate.api.nvidia.com/v1/chat/completions",
  };

  const defaultModels: Record<string, string> = {
    openrouter: "anthropic/claude-3-haiku",
    nvidia_nim: "meta/llama-3.1-70b-instruct",
  };

  // Auto-fill defaults when type changes (only for new providers)
  useEffect(() => {
    if (!isEdit && providerType) {
      if (!endpointUrl) setEndpointUrl(defaultEndpoints[providerType] ?? "");
      if (!model) setModel(defaultModels[providerType] ?? "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providerType]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>{isEdit ? "Edit Provider" : "Add AI Provider"}</DialogTitle>
        <DialogDescription>
          {isEdit
            ? "Update the provider configuration."
            : "Configure a new AI provider for market analysis."}
        </DialogDescription>
      </DialogHeader>

      <form onSubmit={handleSubmit} className="space-y-4">
        {error && (
          <p className="text-sm text-red-500">{error}</p>
        )}

        <div className="space-y-2">
          <label className="text-sm font-medium">Name</label>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Claude via OpenRouter"
            required
          />
        </div>

        {!isEdit && (
          <div className="space-y-2">
            <label className="text-sm font-medium">Provider Type</label>
            <Select
              value={providerType}
              onChange={(e) => {
                setProviderType(e.target.value);
                setEndpointUrl(defaultEndpoints[e.target.value] ?? "");
                setModel(defaultModels[e.target.value] ?? "");
              }}
              required
            >
              <option value="" disabled>
                Select type
              </option>
              {providerTypes.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </Select>
          </div>
        )}

        <div className="space-y-2">
          <label className="text-sm font-medium">Endpoint URL</label>
          <Input
            value={endpointUrl}
            onChange={(e) => setEndpointUrl(e.target.value)}
            placeholder="https://..."
            required
          />
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium">Model</label>
          <Input
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="e.g. anthropic/claude-3-haiku"
            required
          />
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium">
            API Key {isEdit && "(leave blank to keep existing)"}
          </label>
          <Input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={isEdit ? "••••••••" : "sk-..."}
            required={!isEdit}
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <label className="text-sm font-medium">Max Tokens</label>
            <Input
              type="number"
              min={1}
              max={16384}
              value={maxTokens}
              onChange={(e) => setMaxTokens(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Temperature</label>
            <Input
              type="number"
              min={0}
              max={2}
              step={0.1}
              value={temperature}
              onChange={(e) => setTemperature(e.target.value)}
            />
          </div>
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button type="submit" disabled={saving}>
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {isEdit ? "Save Changes" : "Add Provider"}
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  );
}
