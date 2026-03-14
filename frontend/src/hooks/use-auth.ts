"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/stores/auth-store";
import { usePlanStore } from "@/stores/plan-store";
import { apiClient } from "@/lib/api-client";

export function useAuth({ redirect = true } = {}) {
  const router = useRouter();
  const { user, isAuthenticated, setUser, logout } = useAuthStore();
  const setSummary = usePlanStore((s) => s.setSummary);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (token && !user) {
      apiClient
        .get("/api/v1/users/me")
        .then((res) => {
          setUser(res.data);
          return apiClient.get("/api/v1/subscriptions/me/summary");
        })
        .then((res) => setSummary(res.data))
        .catch(() => {
          logout();
          if (redirect) router.push("/login");
        });
    } else if (!token && redirect) {
      router.push("/login");
    }
  }, [user, setUser, setSummary, logout, router, redirect]);

  return { user, isAuthenticated, logout };
}
