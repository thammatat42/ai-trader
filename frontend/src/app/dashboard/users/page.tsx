"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Shield,
  ShieldOff,
  Users as UsersIcon,
  Search,
  Plus,
  Ban,
  Unlock,
  KeyRound,
  Eye,
  Activity,
  UserCheck,
  UserX,
  Globe,
  Monitor,
  CheckCircle2,
  XCircle,
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
import { useAuth } from "@/hooks/use-auth";
import type { UserDetail, LoginActivity } from "@/types/api";

// ---- Constants ----

const ROLE_COLORS: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  admin: "default",
  trader: "secondary",
  viewer: "outline",
};

type Tab = "users" | "activity";

// ---- Page ----

export default function UserManagementPage() {
  const { user: currentUser } = useAuth();
  const queryClient = useQueryClient();

  // Tab state
  const [activeTab, setActiveTab] = useState<Tab>("users");

  // Filters
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  // Expanded user detail
  const [expandedUserId, setExpandedUserId] = useState<string | null>(null);

  // Dialogs
  const [createOpen, setCreateOpen] = useState(false);
  const [banDialogUser, setBanDialogUser] = useState<UserDetail | null>(null);
  const [resetPwUser, setResetPwUser] = useState<UserDetail | null>(null);

  // Form states
  const [createForm, setCreateForm] = useState({
    email: "",
    password: "",
    full_name: "",
    role: "trader",
  });
  const [banReason, setBanReason] = useState("");
  const [newPassword, setNewPassword] = useState("");

  // ---- Queries ----

  const {
    data: users = [],
    isLoading,
  } = useQuery<UserDetail[]>({
    queryKey: ["users", search, roleFilter, statusFilter],
    queryFn: () => {
      const params = new URLSearchParams();
      if (search) params.set("search", search);
      if (roleFilter) params.set("role", roleFilter);
      if (statusFilter) params.set("status", statusFilter);
      const qs = params.toString();
      return apiClient.get(`/api/v1/users${qs ? `?${qs}` : ""}`).then((r) => r.data);
    },
    enabled: currentUser?.role === "admin",
  });

  const { data: loginActivities = [], isLoading: activityLoading } = useQuery<LoginActivity[]>({
    queryKey: ["login-activity"],
    queryFn: () => apiClient.get("/api/v1/users/login-activity?limit=100").then((r) => r.data),
    enabled: currentUser?.role === "admin" && activeTab === "activity",
  });

  // ---- Mutations ----

  const createUserMutation = useMutation({
    mutationFn: (data: typeof createForm) =>
      apiClient.post("/api/v1/users", data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      setCreateOpen(false);
      setCreateForm({ email: "", password: "", full_name: "", role: "trader" });
    },
  });

  const roleMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) =>
      apiClient.put(`/api/v1/users/${userId}/role`, { role }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["users"] }),
  });

  const activateMutation = useMutation({
    mutationFn: (userId: string) =>
      apiClient.put(`/api/v1/users/${userId}/activate`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["users"] }),
  });

  const deactivateMutation = useMutation({
    mutationFn: (userId: string) =>
      apiClient.put(`/api/v1/users/${userId}/deactivate`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["users"] }),
  });

  const banMutation = useMutation({
    mutationFn: ({ userId, reason }: { userId: string; reason: string }) =>
      apiClient.post(`/api/v1/users/${userId}/ban`, { reason }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      setBanDialogUser(null);
      setBanReason("");
    },
  });

  const unbanMutation = useMutation({
    mutationFn: (userId: string) =>
      apiClient.post(`/api/v1/users/${userId}/unban`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["users"] }),
  });

  const unlockMutation = useMutation({
    mutationFn: (userId: string) =>
      apiClient.post(`/api/v1/users/${userId}/unlock`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["users"] }),
  });

  const resetPwMutation = useMutation({
    mutationFn: ({ userId, new_password }: { userId: string; new_password: string }) =>
      apiClient.post(`/api/v1/users/${userId}/reset-password`, { new_password }),
    onSuccess: () => {
      setResetPwUser(null);
      setNewPassword("");
    },
  });

  // ---- Access guard ----

  if (currentUser?.role !== "admin") {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-20 text-muted-foreground">
        <Shield className="h-10 w-10" />
        <p className="text-lg font-medium">Admin access required</p>
        <p className="text-sm">You don&apos;t have permission to view this page.</p>
      </div>
    );
  }

  // ---- Helpers ---- 

  function getUserStatus(u: UserDetail) {
    if (u.banned_at) return "banned";
    if (u.locked_until && new Date(u.locked_until) > new Date()) return "locked";
    if (!u.is_active) return "inactive";
    return "active";
  }

  function getStatusBadge(u: UserDetail) {
    const status = getUserStatus(u);
    switch (status) {
      case "banned":
        return <Badge variant="destructive">Banned</Badge>;
      case "locked":
        return (
          <Badge variant="destructive" className="bg-orange-600">
            Locked
          </Badge>
        );
      case "inactive":
        return <Badge variant="secondary">Inactive</Badge>;
      default:
        return (
          <Badge variant="outline" className="border-green-600 text-green-600">
            Active
          </Badge>
        );
    }
  }

  // ---- Per-user login activity ----

  function UserLoginActivity({ userId }: { userId: string }) {
    const { data: activities = [], isLoading: loading } = useQuery<LoginActivity[]>({
      queryKey: ["user-login-activity", userId],
      queryFn: () =>
        apiClient.get(`/api/v1/users/${userId}/login-activity?limit=20`).then((r) => r.data),
    });

    if (loading) return <p className="text-xs text-muted-foreground">Loading activity...</p>;
    if (activities.length === 0)
      return <p className="text-xs text-muted-foreground">No login activity recorded.</p>;

    return (
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              <th className="pb-2 pr-3">Time</th>
              <th className="pb-2 pr-3">Status</th>
              <th className="pb-2 pr-3">IP</th>
              <th className="pb-2 pr-3">Location</th>
              <th className="pb-2 pr-3">User Agent</th>
              <th className="pb-2">Reason</th>
            </tr>
          </thead>
          <tbody>
            {activities.map((a) => (
              <tr key={a.id} className="border-b border-border/50">
                <td className="py-1.5 pr-3 whitespace-nowrap">
                  {new Date(a.created_at).toLocaleString()}
                </td>
                <td className="py-1.5 pr-3">
                  {a.success ? (
                    <span className="flex items-center gap-1 text-green-500">
                      <CheckCircle2 className="h-3 w-3" /> OK
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 text-red-500">
                      <XCircle className="h-3 w-3" /> Fail
                    </span>
                  )}
                </td>
                <td className="py-1.5 pr-3 font-mono">{a.ip_address || "—"}</td>
                <td className="py-1.5 pr-3">
                  {a.country || a.city ? (
                    <span className="flex items-center gap-1">
                      <Globe className="h-3 w-3" />
                      {[a.city, a.country].filter(Boolean).join(", ")}
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="py-1.5 pr-3 max-w-[200px] truncate" title={a.user_agent || ""}>
                  <span className="flex items-center gap-1">
                    <Monitor className="h-3 w-3 shrink-0" />
                    {a.user_agent
                      ? a.user_agent.length > 50
                        ? a.user_agent.substring(0, 50) + "…"
                        : a.user_agent
                      : "—"}
                  </span>
                </td>
                <td className="py-1.5 text-orange-400">{a.failure_reason || ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  // ---- Render ----

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">User Management</h1>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="mr-2 h-4 w-4" /> Create User
        </Button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 rounded-lg bg-muted p-1">
        <button
          onClick={() => setActiveTab("users")}
          className={`flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
            activeTab === "users"
              ? "bg-background text-foreground shadow"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          <UsersIcon className="h-4 w-4" /> Users ({users.length})
        </button>
        <button
          onClick={() => setActiveTab("activity")}
          className={`flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
            activeTab === "activity"
              ? "bg-background text-foreground shadow"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          <Activity className="h-4 w-4" /> Login Activity
        </button>
      </div>

      {/* ===== USERS TAB ===== */}
      {activeTab === "users" && (
        <>
          {/* Filters */}
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative flex-1 min-w-[200px]">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Search by email or name..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-9"
              />
            </div>
            <Select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
              <option value="">All Roles</option>
              <option value="admin">Admin</option>
              <option value="trader">Trader</option>
              <option value="viewer">Viewer</option>
            </Select>
            <Select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">All Status</option>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
              <option value="banned">Banned</option>
              <option value="locked">Locked</option>
            </Select>
          </div>

          {/* Users List */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <UsersIcon className="h-5 w-5" /> All Users
              </CardTitle>
              <CardDescription>
                {users.length} user{users.length !== 1 ? "s" : ""} found
              </CardDescription>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <p className="text-sm text-muted-foreground">Loading...</p>
              ) : users.length === 0 ? (
                <div className="flex flex-col items-center gap-2 py-8 text-muted-foreground">
                  <UsersIcon className="h-8 w-8" />
                  <p className="text-sm">No users match the filters.</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {users.map((u) => {
                    const isExpanded = expandedUserId === u.id;
                    const isSelf = u.id === currentUser?.id;
                    const status = getUserStatus(u);

                    return (
                      <div
                        key={u.id}
                        className="rounded-lg border border-border transition-colors"
                      >
                        {/* User row */}
                        <div className="flex items-center justify-between px-4 py-3">
                          <div className="flex-1 space-y-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-medium">
                                {u.full_name || u.email.split("@")[0]}
                              </span>
                              <Badge variant={ROLE_COLORS[u.role] ?? "secondary"}>
                                {u.role}
                              </Badge>
                              {getStatusBadge(u)}
                              {isSelf && (
                                <Badge variant="outline" className="text-xs">
                                  You
                                </Badge>
                              )}
                            </div>
                            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                              <span>{u.email}</span>
                              <span>
                                Joined: {new Date(u.created_at).toLocaleDateString()}
                              </span>
                              {u.last_login_at && (
                                <span>
                                  Last login: {new Date(u.last_login_at).toLocaleString()}
                                </span>
                              )}
                              {u.failed_login_count > 0 && (
                                <span className="text-orange-400">
                                  Failed logins: {u.failed_login_count}
                                </span>
                              )}
                            </div>
                            {u.ban_reason && (
                              <p className="text-xs text-red-400">
                                Ban reason: {u.ban_reason}
                              </p>
                            )}
                          </div>

                          <div className="flex items-center gap-1">
                            {!isSelf && (
                              <>
                                {/* Role dropdown */}
                                <Select
                                  className="h-8 w-24 text-xs"
                                  value={u.role}
                                  onChange={(e) =>
                                    roleMutation.mutate({
                                      userId: u.id,
                                      role: e.target.value,
                                    })
                                  }
                                  disabled={roleMutation.isPending}
                                >
                                  <option value="admin">Admin</option>
                                  <option value="trader">Trader</option>
                                  <option value="viewer">Viewer</option>
                                </Select>

                                {/* Ban / Unban */}
                                {status === "banned" ? (
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => unbanMutation.mutate(u.id)}
                                    disabled={unbanMutation.isPending}
                                    title="Unban user"
                                  >
                                    <Unlock className="h-3 w-3" />
                                  </Button>
                                ) : (
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="text-destructive hover:text-destructive"
                                    onClick={() => setBanDialogUser(u)}
                                    title="Ban user"
                                  >
                                    <Ban className="h-3 w-3" />
                                  </Button>
                                )}

                                {/* Unlock locked */}
                                {status === "locked" && (
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => unlockMutation.mutate(u.id)}
                                    disabled={unlockMutation.isPending}
                                    title="Unlock account"
                                  >
                                    <Unlock className="h-3 w-3" />
                                  </Button>
                                )}

                                {/* Activate / Deactivate */}
                                {u.is_active ? (
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => deactivateMutation.mutate(u.id)}
                                    disabled={deactivateMutation.isPending}
                                    title="Deactivate"
                                  >
                                    <UserX className="h-3 w-3" />
                                  </Button>
                                ) : status !== "banned" ? (
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => activateMutation.mutate(u.id)}
                                    disabled={activateMutation.isPending}
                                    title="Activate"
                                  >
                                    <UserCheck className="h-3 w-3" />
                                  </Button>
                                ) : null}

                                {/* Reset password */}
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => setResetPwUser(u)}
                                  title="Reset password"
                                >
                                  <KeyRound className="h-3 w-3" />
                                </Button>
                              </>
                            )}

                            {/* Expand detail */}
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() =>
                                setExpandedUserId(isExpanded ? null : u.id)
                              }
                              title="View login activity"
                            >
                              {isExpanded ? (
                                <ChevronUp className="h-3 w-3" />
                              ) : (
                                <ChevronDown className="h-3 w-3" />
                              )}
                            </Button>
                          </div>
                        </div>

                        {/* Expanded: login activity */}
                        {isExpanded && (
                          <div className="border-t border-border bg-muted/30 px-4 py-3">
                            <h4 className="mb-2 text-sm font-medium flex items-center gap-1">
                              <Activity className="h-3.5 w-3.5" /> Recent Login Activity
                            </h4>
                            <UserLoginActivity userId={u.id} />
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}

      {/* ===== LOGIN ACTIVITY TAB ===== */}
      {activeTab === "activity" && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="h-5 w-5" /> All Login Activity
            </CardTitle>
            <CardDescription>
              Last 100 login attempts across all users
            </CardDescription>
          </CardHeader>
          <CardContent>
            {activityLoading ? (
              <p className="text-sm text-muted-foreground">Loading...</p>
            ) : loginActivities.length === 0 ? (
              <p className="text-sm text-muted-foreground">No login activity yet.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-muted-foreground">
                      <th className="pb-2 pr-4">Time</th>
                      <th className="pb-2 pr-4">Email</th>
                      <th className="pb-2 pr-4">Status</th>
                      <th className="pb-2 pr-4">IP Address</th>
                      <th className="pb-2 pr-4">Location</th>
                      <th className="pb-2 pr-4">User Agent</th>
                      <th className="pb-2">Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {loginActivities.map((a) => (
                      <tr key={a.id} className="border-b border-border/50 hover:bg-muted/30">
                        <td className="py-2 pr-4 whitespace-nowrap text-xs">
                          {new Date(a.created_at).toLocaleString()}
                        </td>
                        <td className="py-2 pr-4 text-xs">{a.email}</td>
                        <td className="py-2 pr-4">
                          {a.success ? (
                            <span className="flex items-center gap-1 text-xs text-green-500">
                              <CheckCircle2 className="h-3.5 w-3.5" /> Success
                            </span>
                          ) : (
                            <span className="flex items-center gap-1 text-xs text-red-500">
                              <XCircle className="h-3.5 w-3.5" /> Failed
                            </span>
                          )}
                        </td>
                        <td className="py-2 pr-4 font-mono text-xs">
                          {a.ip_address || "—"}
                        </td>
                        <td className="py-2 pr-4 text-xs">
                          {a.country || a.city ? (
                            <span className="flex items-center gap-1">
                              <Globe className="h-3 w-3" />
                              {[a.city, a.country].filter(Boolean).join(", ")}
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td
                          className="py-2 pr-4 text-xs max-w-[250px] truncate"
                          title={a.user_agent || ""}
                        >
                          {a.user_agent
                            ? a.user_agent.length > 60
                              ? a.user_agent.substring(0, 60) + "…"
                              : a.user_agent
                            : "—"}
                        </td>
                        <td className="py-2 text-xs text-orange-400">
                          {a.failure_reason || ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* ===== CREATE USER DIALOG ===== */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogHeader>
          <DialogTitle>Create New User</DialogTitle>
          <DialogDescription>
            Add a new user to the system. They will receive the specified role.
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            createUserMutation.mutate(createForm);
          }}
          className="space-y-4"
        >
          <div>
            <label className="mb-1 block text-sm font-medium">Email</label>
            <Input
              type="email"
              required
              value={createForm.email}
              onChange={(e) =>
                setCreateForm((f) => ({ ...f, email: e.target.value }))
              }
              placeholder="user@example.com"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">Full Name</label>
            <Input
              value={createForm.full_name}
              onChange={(e) =>
                setCreateForm((f) => ({ ...f, full_name: e.target.value }))
              }
              placeholder="John Doe"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">Password</label>
            <Input
              type="password"
              required
              minLength={6}
              value={createForm.password}
              onChange={(e) =>
                setCreateForm((f) => ({ ...f, password: e.target.value }))
              }
              placeholder="Min 6 characters"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">Role</label>
            <Select
              value={createForm.role}
              onChange={(e) =>
                setCreateForm((f) => ({ ...f, role: e.target.value }))
              }
            >
              <option value="trader">Trader</option>
              <option value="viewer">Viewer</option>
              <option value="admin">Admin</option>
            </Select>
          </div>
          {createUserMutation.isError && (
            <p className="text-sm text-red-500">
              {(createUserMutation.error as any)?.response?.data?.detail ||
                "Failed to create user"}
            </p>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => setCreateOpen(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={createUserMutation.isPending}>
              {createUserMutation.isPending ? "Creating..." : "Create User"}
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* ===== BAN USER DIALOG ===== */}
      <Dialog
        open={!!banDialogUser}
        onOpenChange={(open) => {
          if (!open) {
            setBanDialogUser(null);
            setBanReason("");
          }
        }}
      >
        <DialogHeader>
          <DialogTitle>Ban User</DialogTitle>
          <DialogDescription>
            Banning <strong>{banDialogUser?.email}</strong> will immediately
            revoke all access. Provide a reason for the ban.
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (banDialogUser) {
              banMutation.mutate({
                userId: banDialogUser.id,
                reason: banReason,
              });
            }
          }}
          className="space-y-4"
        >
          <div>
            <label className="mb-1 block text-sm font-medium">Ban Reason</label>
            <Input
              required
              value={banReason}
              onChange={(e) => setBanReason(e.target.value)}
              placeholder="e.g. Suspicious login activity, ToS violation..."
            />
          </div>
          {banMutation.isError && (
            <p className="text-sm text-red-500">
              {(banMutation.error as any)?.response?.data?.detail ||
                "Failed to ban user"}
            </p>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setBanDialogUser(null);
                setBanReason("");
              }}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="destructive"
              disabled={banMutation.isPending}
            >
              {banMutation.isPending ? "Banning..." : "Ban User"}
            </Button>
          </DialogFooter>
        </form>
      </Dialog>

      {/* ===== RESET PASSWORD DIALOG ===== */}
      <Dialog
        open={!!resetPwUser}
        onOpenChange={(open) => {
          if (!open) {
            setResetPwUser(null);
            setNewPassword("");
          }
        }}
      >
        <DialogHeader>
          <DialogTitle>Reset Password</DialogTitle>
          <DialogDescription>
            Set a new password for <strong>{resetPwUser?.email}</strong>. This
            will also unlock the account if locked.
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (resetPwUser) {
              resetPwMutation.mutate({
                userId: resetPwUser.id,
                new_password: newPassword,
              });
            }
          }}
          className="space-y-4"
        >
          <div>
            <label className="mb-1 block text-sm font-medium">New Password</label>
            <Input
              type="password"
              required
              minLength={6}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="Min 6 characters"
            />
          </div>
          {resetPwMutation.isError && (
            <p className="text-sm text-red-500">
              {(resetPwMutation.error as any)?.response?.data?.detail ||
                "Failed to reset password"}
            </p>
          )}
          {resetPwMutation.isSuccess && (
            <p className="text-sm text-green-500">Password has been reset successfully.</p>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setResetPwUser(null);
                setNewPassword("");
              }}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={resetPwMutation.isPending}>
              {resetPwMutation.isPending ? "Resetting..." : "Reset Password"}
            </Button>
          </DialogFooter>
        </form>
      </Dialog>
    </div>
  );
}
