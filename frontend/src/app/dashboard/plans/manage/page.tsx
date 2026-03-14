"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Settings2,
  Plus,
  Pencil,
  Trash2,
  Shield,
  Package,
  Check,
  X,
  Loader2,
  ChevronDown,
  ChevronUp,
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
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import {
  Dialog,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { apiClient } from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";
import type {
  Plan,
  Module,
  PlanModule,
  PlanCreateRequest,
  PlanUpdateRequest,
  PlanModuleAssignRequest,
} from "@/types/api";

export default function AdminPlansManagePage() {
  const user = useAuthStore((s) => s.user);
  const queryClient = useQueryClient();

  // State
  const [expandedPlanId, setExpandedPlanId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editPlan, setEditPlan] = useState<Plan | null>(null);
  const [addModulePlanId, setAddModulePlanId] = useState<string | null>(null);

  // Create form
  const [createForm, setCreateForm] = useState<PlanCreateRequest>({
    code: "",
    name: "",
    description: "",
    price_monthly: 0,
    price_yearly: 0,
    ai_credits_monthly: 0,
    max_api_keys: 1,
    max_platforms: 1,
    max_trades_per_day: 5,
    sort_order: 0,
    is_active: true,
    is_default: false,
  });

  // Edit form
  const [editForm, setEditForm] = useState<PlanUpdateRequest>({});

  // Module assign form
  const [moduleAssign, setModuleAssign] = useState<PlanModuleAssignRequest>({
    module_code: "",
    access_level: "full",
    quota_limit: null,
  });

  // ── Queries ──

  const { data: plans = [], isLoading } = useQuery<Plan[]>({
    queryKey: ["admin-plans"],
    queryFn: () => apiClient.get("/api/v1/admin/plans").then((r) => r.data),
    enabled: user?.role === "admin",
  });

  const { data: allModules = [] } = useQuery<Module[]>({
    queryKey: ["all-modules"],
    queryFn: () => apiClient.get("/api/v1/plans/modules/all").then((r) => r.data),
  });

  const { data: planModules = [] } = useQuery<PlanModule[]>({
    queryKey: ["plan-modules", expandedPlanId],
    queryFn: () =>
      apiClient
        .get(`/api/v1/admin/plans/${expandedPlanId}/modules`)
        .then((r) => r.data),
    enabled: !!expandedPlanId,
  });

  // ── Mutations ──

  const createMutation = useMutation({
    mutationFn: (data: PlanCreateRequest) =>
      apiClient.post("/api/v1/admin/plans", data).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-plans"] });
      queryClient.invalidateQueries({ queryKey: ["plans"] });
      setCreateOpen(false);
      setCreateForm({
        code: "",
        name: "",
        description: "",
        price_monthly: 0,
        price_yearly: 0,
        ai_credits_monthly: 0,
        max_api_keys: 1,
        max_platforms: 1,
        max_trades_per_day: 5,
        sort_order: 0,
        is_active: true,
        is_default: false,
      });
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: PlanUpdateRequest }) =>
      apiClient.put(`/api/v1/admin/plans/${id}`, data).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-plans"] });
      queryClient.invalidateQueries({ queryKey: ["plans"] });
      setEditPlan(null);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) =>
      apiClient.delete(`/api/v1/admin/plans/${id}`).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-plans"] });
      queryClient.invalidateQueries({ queryKey: ["plans"] });
    },
  });

  const addModuleMutation = useMutation({
    mutationFn: ({
      planId,
      data,
    }: {
      planId: string;
      data: PlanModuleAssignRequest;
    }) =>
      apiClient
        .post(`/api/v1/admin/plans/${planId}/modules`, data)
        .then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["plan-modules", expandedPlanId],
      });
      queryClient.invalidateQueries({ queryKey: ["plans"] });
      setAddModulePlanId(null);
      setModuleAssign({ module_code: "", access_level: "full", quota_limit: null });
    },
  });

  const removeModuleMutation = useMutation({
    mutationFn: ({
      planId,
      moduleCode,
    }: {
      planId: string;
      moduleCode: string;
    }) =>
      apiClient
        .delete(`/api/v1/admin/plans/${planId}/modules/${moduleCode}`)
        .then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["plan-modules", expandedPlanId],
      });
      queryClient.invalidateQueries({ queryKey: ["plans"] });
    },
  });

  // ── Access guard ──

  if (user?.role !== "admin") {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-20 text-muted-foreground">
        <Shield className="h-10 w-10" />
        <p className="text-lg font-medium">Admin access required</p>
      </div>
    );
  }

  // Get assigned module codes for filtering
  const assignedModuleCodes = planModules.map((pm) => pm.module.code);
  const availableModules = allModules.filter(
    (m) => !assignedModuleCodes.includes(m.code)
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Plan Management</h1>
          <p className="mt-1 text-muted-foreground">
            Create, edit plans and manage module access per plan
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="mr-2 h-4 w-4" /> Create Plan
        </Button>
      </div>

      {/* Plans List */}
      {isLoading ? (
        <div className="flex justify-center py-10">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <div className="space-y-3">
          {plans.map((plan) => {
            const isExpanded = expandedPlanId === plan.id;
            return (
              <Card key={plan.id}>
                {/* Plan Header Row */}
                <div className="flex items-center justify-between px-6 py-4">
                  <div className="flex-1 space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-lg">{plan.name}</span>
                      <Badge variant="secondary" className="font-mono text-xs">
                        {plan.code}
                      </Badge>
                      {plan.is_active ? (
                        <Badge
                          variant="outline"
                          className="border-green-600 text-green-600 text-xs"
                        >
                          Active
                        </Badge>
                      ) : (
                        <Badge variant="destructive" className="text-xs">
                          Inactive
                        </Badge>
                      )}
                      {plan.is_default && (
                        <Badge className="text-xs">Default</Badge>
                      )}
                    </div>
                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                      <span>
                        ${plan.price_monthly}/mo · ${plan.price_yearly}/yr
                      </span>
                      <span>{plan.ai_credits_monthly} credits/mo</span>
                      <span>
                        {plan.max_platforms} platform
                        {plan.max_platforms !== 1 ? "s" : ""}
                      </span>
                      <span>
                        {plan.max_trades_per_day >= 9999
                          ? "Unlimited"
                          : plan.max_trades_per_day}{" "}
                        trades/day
                      </span>
                      <span>
                        {plan.max_api_keys >= 9999
                          ? "Unlimited"
                          : plan.max_api_keys}{" "}
                        API keys
                      </span>
                    </div>
                    {plan.description && (
                      <p className="text-xs text-muted-foreground mt-1">
                        {plan.description}
                      </p>
                    )}
                  </div>

                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setEditPlan(plan);
                        setEditForm({
                          name: plan.name,
                          description: plan.description ?? "",
                          price_monthly: plan.price_monthly,
                          price_yearly: plan.price_yearly,
                          ai_credits_monthly: plan.ai_credits_monthly,
                          max_api_keys: plan.max_api_keys,
                          max_platforms: plan.max_platforms,
                          max_trades_per_day: plan.max_trades_per_day,
                          sort_order: plan.sort_order,
                          is_active: plan.is_active,
                          is_default: plan.is_default,
                        });
                      }}
                      title="Edit plan"
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-destructive hover:text-destructive"
                      onClick={() => {
                        if (
                          confirm(
                            `Deactivate plan "${plan.name}"? Users on this plan won't lose access immediately.`
                          )
                        ) {
                          deleteMutation.mutate(plan.id);
                        }
                      }}
                      title="Deactivate plan"
                      disabled={deleteMutation.isPending}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        setExpandedPlanId(isExpanded ? null : plan.id)
                      }
                      title="Manage modules"
                    >
                      {isExpanded ? (
                        <ChevronUp className="h-4 w-4" />
                      ) : (
                        <ChevronDown className="h-4 w-4" />
                      )}
                    </Button>
                  </div>
                </div>

                {/* Expanded: Modules */}
                {isExpanded && (
                  <div className="border-t border-border bg-muted/30 px-6 py-4">
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="text-sm font-medium flex items-center gap-2">
                        <Package className="h-4 w-4" /> Included Modules (
                        {planModules.length})
                      </h3>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setAddModulePlanId(plan.id)}
                        disabled={availableModules.length === 0}
                      >
                        <Plus className="mr-1 h-3 w-3" /> Add Module
                      </Button>
                    </div>

                    {planModules.length === 0 ? (
                      <p className="text-sm text-muted-foreground py-2">
                        No modules assigned to this plan.
                      </p>
                    ) : (
                      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                        {planModules.map((pm) => (
                          <div
                            key={pm.module.id}
                            className="flex items-center justify-between rounded-md border border-border p-3 text-sm"
                          >
                            <div className="flex items-center gap-2">
                              <Check className="h-4 w-4 text-green-500 shrink-0" />
                              <div>
                                <span className="font-medium">
                                  {pm.module.name}
                                </span>
                                {pm.access_level !== "full" && (
                                  <Badge
                                    variant="secondary"
                                    className="ml-2 text-xs"
                                  >
                                    {pm.access_level}
                                  </Badge>
                                )}
                              </div>
                            </div>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="text-destructive hover:text-destructive h-7 w-7 p-0"
                              onClick={() =>
                                removeModuleMutation.mutate({
                                  planId: plan.id,
                                  moduleCode: pm.module.code,
                                })
                              }
                              disabled={removeModuleMutation.isPending}
                              title="Remove module"
                            >
                              <X className="h-3 w-3" />
                            </Button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      )}

      {/* ── Create Plan Dialog ── */}
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)}>
        <DialogHeader>
          <DialogTitle>Create New Plan</DialogTitle>
          <DialogDescription>
            Define a new subscription plan with pricing and limits.
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            createMutation.mutate(createForm);
          }}
        >
          <div className="space-y-3 py-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-muted-foreground">
                  Code
                </label>
                <Input
                  required
                  placeholder="e.g. premium"
                  value={createForm.code}
                  onChange={(e) =>
                    setCreateForm({ ...createForm, code: e.target.value })
                  }
                />
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground">
                  Name
                </label>
                <Input
                  required
                  placeholder="e.g. Premium"
                  value={createForm.name}
                  onChange={(e) =>
                    setCreateForm({ ...createForm, name: e.target.value })
                  }
                />
              </div>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground">
                Description
              </label>
              <Input
                placeholder="Plan description"
                value={createForm.description ?? ""}
                onChange={(e) =>
                  setCreateForm({ ...createForm, description: e.target.value })
                }
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-muted-foreground">
                  Monthly Price ($)
                </label>
                <Input
                  type="number"
                  step="0.01"
                  min="0"
                  value={createForm.price_monthly}
                  onChange={(e) =>
                    setCreateForm({
                      ...createForm,
                      price_monthly: parseFloat(e.target.value) || 0,
                    })
                  }
                />
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground">
                  Yearly Price ($)
                </label>
                <Input
                  type="number"
                  step="0.01"
                  min="0"
                  value={createForm.price_yearly}
                  onChange={(e) =>
                    setCreateForm({
                      ...createForm,
                      price_yearly: parseFloat(e.target.value) || 0,
                    })
                  }
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-muted-foreground">
                  AI Credits / Month
                </label>
                <Input
                  type="number"
                  min="0"
                  value={createForm.ai_credits_monthly}
                  onChange={(e) =>
                    setCreateForm({
                      ...createForm,
                      ai_credits_monthly: parseInt(e.target.value) || 0,
                    })
                  }
                />
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground">
                  Max Platforms
                </label>
                <Input
                  type="number"
                  min="1"
                  value={createForm.max_platforms}
                  onChange={(e) =>
                    setCreateForm({
                      ...createForm,
                      max_platforms: parseInt(e.target.value) || 1,
                    })
                  }
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-muted-foreground">
                  Max Trades / Day
                </label>
                <Input
                  type="number"
                  min="1"
                  value={createForm.max_trades_per_day}
                  onChange={(e) =>
                    setCreateForm({
                      ...createForm,
                      max_trades_per_day: parseInt(e.target.value) || 5,
                    })
                  }
                />
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground">
                  Max API Keys
                </label>
                <Input
                  type="number"
                  min="1"
                  value={createForm.max_api_keys}
                  onChange={(e) =>
                    setCreateForm({
                      ...createForm,
                      max_api_keys: parseInt(e.target.value) || 1,
                    })
                  }
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-muted-foreground">
                  Sort Order
                </label>
                <Input
                  type="number"
                  value={createForm.sort_order}
                  onChange={(e) =>
                    setCreateForm({
                      ...createForm,
                      sort_order: parseInt(e.target.value) || 0,
                    })
                  }
                />
              </div>
              <div className="flex items-end gap-4">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={createForm.is_active}
                    onChange={(e) =>
                      setCreateForm({
                        ...createForm,
                        is_active: e.target.checked,
                      })
                    }
                    className="rounded"
                  />
                  Active
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={createForm.is_default}
                    onChange={(e) =>
                      setCreateForm({
                        ...createForm,
                        is_default: e.target.checked,
                      })
                    }
                    className="rounded"
                  />
                  Default
                </label>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setCreateOpen(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={createMutation.isPending}>
              {createMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : null}
              Create Plan
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* ── Edit Plan Dialog ── */}
      <Dialog open={!!editPlan} onClose={() => setEditPlan(null)}>
        <DialogHeader>
          <DialogTitle>
            Edit Plan: {editPlan?.name}{" "}
            <Badge variant="secondary" className="font-mono text-xs ml-2">
              {editPlan?.code}
            </Badge>
          </DialogTitle>
          <DialogDescription>
            Update plan details, pricing, and limits.
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (editPlan) {
              updateMutation.mutate({ id: editPlan.id, data: editForm });
            }
          }}
        >
          <div className="space-y-3 py-4">
            <div>
              <label className="text-xs font-medium text-muted-foreground">
                Name
              </label>
              <Input
                value={editForm.name ?? ""}
                onChange={(e) =>
                  setEditForm({ ...editForm, name: e.target.value })
                }
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground">
                Description
              </label>
              <Input
                value={editForm.description ?? ""}
                onChange={(e) =>
                  setEditForm({ ...editForm, description: e.target.value })
                }
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-muted-foreground">
                  Monthly Price ($)
                </label>
                <Input
                  type="number"
                  step="0.01"
                  min="0"
                  value={editForm.price_monthly ?? 0}
                  onChange={(e) =>
                    setEditForm({
                      ...editForm,
                      price_monthly: parseFloat(e.target.value) || 0,
                    })
                  }
                />
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground">
                  Yearly Price ($)
                </label>
                <Input
                  type="number"
                  step="0.01"
                  min="0"
                  value={editForm.price_yearly ?? 0}
                  onChange={(e) =>
                    setEditForm({
                      ...editForm,
                      price_yearly: parseFloat(e.target.value) || 0,
                    })
                  }
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-muted-foreground">
                  AI Credits / Month
                </label>
                <Input
                  type="number"
                  min="0"
                  value={editForm.ai_credits_monthly ?? 0}
                  onChange={(e) =>
                    setEditForm({
                      ...editForm,
                      ai_credits_monthly: parseInt(e.target.value) || 0,
                    })
                  }
                />
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground">
                  Max Platforms
                </label>
                <Input
                  type="number"
                  min="1"
                  value={editForm.max_platforms ?? 1}
                  onChange={(e) =>
                    setEditForm({
                      ...editForm,
                      max_platforms: parseInt(e.target.value) || 1,
                    })
                  }
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-muted-foreground">
                  Max Trades / Day
                </label>
                <Input
                  type="number"
                  min="1"
                  value={editForm.max_trades_per_day ?? 5}
                  onChange={(e) =>
                    setEditForm({
                      ...editForm,
                      max_trades_per_day: parseInt(e.target.value) || 5,
                    })
                  }
                />
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground">
                  Max API Keys
                </label>
                <Input
                  type="number"
                  min="1"
                  value={editForm.max_api_keys ?? 1}
                  onChange={(e) =>
                    setEditForm({
                      ...editForm,
                      max_api_keys: parseInt(e.target.value) || 1,
                    })
                  }
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-muted-foreground">
                  Sort Order
                </label>
                <Input
                  type="number"
                  value={editForm.sort_order ?? 0}
                  onChange={(e) =>
                    setEditForm({
                      ...editForm,
                      sort_order: parseInt(e.target.value) || 0,
                    })
                  }
                />
              </div>
              <div className="flex items-end gap-4">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={editForm.is_active ?? true}
                    onChange={(e) =>
                      setEditForm({
                        ...editForm,
                        is_active: e.target.checked,
                      })
                    }
                    className="rounded"
                  />
                  Active
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={editForm.is_default ?? false}
                    onChange={(e) =>
                      setEditForm({
                        ...editForm,
                        is_default: e.target.checked,
                      })
                    }
                    className="rounded"
                  />
                  Default
                </label>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setEditPlan(null)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={updateMutation.isPending}>
              {updateMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : null}
              Save Changes
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* ── Add Module Dialog ── */}
      <Dialog
        open={!!addModulePlanId}
        onClose={() => setAddModulePlanId(null)}
      >
        <DialogHeader>
          <DialogTitle>Add Module to Plan</DialogTitle>
          <DialogDescription>
            Select a module and set its access level for this plan.
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (addModulePlanId && moduleAssign.module_code) {
              addModuleMutation.mutate({
                planId: addModulePlanId,
                data: moduleAssign,
              });
            }
          }}
        >
          <div className="space-y-3 py-4">
            <div>
              <label className="text-xs font-medium text-muted-foreground">
                Module
              </label>
              <Select
                value={moduleAssign.module_code}
                onChange={(e) =>
                  setModuleAssign({
                    ...moduleAssign,
                    module_code: e.target.value,
                  })
                }
                required
              >
                <option value="">Select a module...</option>
                {availableModules.map((m) => (
                  <option key={m.id} value={m.code}>
                    {m.name} ({m.code})
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground">
                Access Level
              </label>
              <Select
                value={moduleAssign.access_level}
                onChange={(e) =>
                  setModuleAssign({
                    ...moduleAssign,
                    access_level: e.target.value,
                  })
                }
              >
                <option value="full">Full</option>
                <option value="readonly">Read Only</option>
                <option value="limited">Limited</option>
              </Select>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground">
                Quota Limit (optional)
              </label>
              <Input
                type="number"
                min="0"
                placeholder="Leave empty for unlimited"
                value={moduleAssign.quota_limit ?? ""}
                onChange={(e) =>
                  setModuleAssign({
                    ...moduleAssign,
                    quota_limit: e.target.value
                      ? parseInt(e.target.value)
                      : null,
                  })
                }
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setAddModulePlanId(null)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={addModuleMutation.isPending}>
              {addModuleMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : null}
              Add Module
            </Button>
          </DialogFooter>
        </form>
      </Dialog>
    </div>
  );
}
