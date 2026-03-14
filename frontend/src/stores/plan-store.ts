import { create } from "zustand";
import type { UserPlanSummary } from "@/types/api";

interface PlanState {
  summary: UserPlanSummary | null;
  setSummary: (summary: UserPlanSummary | null) => void;
  hasModule: (moduleCode: string) => boolean;
  clear: () => void;
}

export const usePlanStore = create<PlanState>((set, get) => ({
  summary: null,
  setSummary: (summary) => set({ summary }),
  hasModule: (moduleCode: string) => {
    const s = get().summary;
    if (!s) return false;
    return s.modules.includes(moduleCode);
  },
  clear: () => set({ summary: null }),
}));
