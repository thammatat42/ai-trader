"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Shield, ShieldOff, Users as UsersIcon } from "lucide-react";
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
import { useAuth } from "@/hooks/use-auth";
import type { User } from "@/types/api";

const ROLE_COLORS: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  admin: "default",
  trader: "secondary",
  viewer: "outline",
};

export default function UserManagementPage() {
  const { user: currentUser } = useAuth();
  const queryClient = useQueryClient();

  const { data: users = [], isLoading } = useQuery<User[]>({
    queryKey: ["users"],
    queryFn: () => apiClient.get("/api/v1/users").then((r) => r.data),
    enabled: currentUser?.role === "admin",
  });

  const roleMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) =>
      apiClient.put(`/api/v1/users/${userId}/role`, { role }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["users"] }),
  });

  const deactivateMutation = useMutation({
    mutationFn: (userId: string) =>
      apiClient.put(`/api/v1/users/${userId}/deactivate`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["users"] }),
  });

  if (currentUser?.role !== "admin") {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-20 text-muted-foreground">
        <Shield className="h-10 w-10" />
        <p className="text-lg font-medium">Admin access required</p>
        <p className="text-sm">You don&apos;t have permission to view this page.</p>
      </div>
    );
  }

  function cycleRole(user: User) {
    const roles = ["admin", "trader", "viewer"];
    const nextIdx = (roles.indexOf(user.role) + 1) % roles.length;
    roleMutation.mutate({ userId: user.id, role: roles[nextIdx] });
  }

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">User Management</h1>

      <Card>
        <CardHeader>
          <CardTitle>All Users</CardTitle>
          <CardDescription>
            {users.length} user{users.length !== 1 ? "s" : ""} registered
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : users.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-8 text-muted-foreground">
              <UsersIcon className="h-8 w-8" />
              <p className="text-sm">No users found.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {users.map((u) => (
                <div
                  key={u.id}
                  className="flex items-center justify-between rounded-md border px-4 py-3"
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">
                        {u.full_name || u.email}
                      </span>
                      <Badge variant={ROLE_COLORS[u.role] ?? "secondary"}>
                        {u.role}
                      </Badge>
                      {!u.is_active && (
                        <Badge variant="destructive">Inactive</Badge>
                      )}
                      {u.id === currentUser?.id && (
                        <Badge variant="outline" className="text-xs">
                          You
                        </Badge>
                      )}
                    </div>
                    <div className="flex gap-4 text-xs text-muted-foreground">
                      <span>{u.email}</span>
                      <span>
                        Joined:{" "}
                        {new Date(u.created_at).toLocaleDateString()}
                      </span>
                    </div>
                  </div>

                  {u.id !== currentUser?.id && (
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => cycleRole(u)}
                        disabled={roleMutation.isPending}
                        title="Cycle role: admin → trader → viewer"
                      >
                        <Shield className="mr-1 h-3 w-3" />
                        Change Role
                      </Button>
                      {u.is_active && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive hover:text-destructive"
                          onClick={() => deactivateMutation.mutate(u.id)}
                          disabled={deactivateMutation.isPending}
                        >
                          <ShieldOff className="mr-1 h-3 w-3" />
                          Deactivate
                        </Button>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
