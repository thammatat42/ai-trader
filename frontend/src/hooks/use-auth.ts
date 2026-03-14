"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/stores/auth-store";
import { apiClient } from "@/lib/api-client";

export function useAuth() {
  const router = useRouter();
  const { user, isAuthenticated, setUser, logout } = useAuthStore();

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (token && !user) {
      apiClient
        .get("/api/v1/auth/me")
        .then((res) => setUser(res.data))
        .catch(() => {
          logout();
          router.push("/login");
        });
    }
  }, [user, setUser, logout, router]);

  return { user, isAuthenticated, logout };
}
