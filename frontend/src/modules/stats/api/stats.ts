import { api, getEveryPage } from "@/lib/api/client";
import type {
  OverviewStats,
  StorageStats,
  CategoryStats,
  ExpiryForecast,
} from "@/types";
import type {
  CostAnalysis,
  RotationAnalysis,
  SmartAlerts,
  ExpenseForecast,
  PurchasePatterns,
  Reconciliation,
} from "@/modules/stats/types/analytics";

export const statsApi = {
  getOverview: async (): Promise<OverviewStats> => {
    const response = await api.get<OverviewStats>("/stats/overview");
    return response.data;
  },

  // Both breakdowns are drawn whole: every bar is scaled against the largest.
  getByStorage: async (): Promise<StorageStats[]> => {
    return getEveryPage<StorageStats>("/stats/by-location");
  },

  getByCategory: async (): Promise<CategoryStats[]> => {
    return getEveryPage<CategoryStats>("/stats/by-category");
  },

  getExpiryForecast: async (): Promise<ExpiryForecast[]> => {
    const response = await api.get<ExpiryForecast[]>("/stats/expiry-forecast");
    return response.data;
  },

  getCostAnalysis: async (period: string = "month"): Promise<CostAnalysis> => {
    const response = await api.get<CostAnalysis>("/stats/cost-analysis", {
      params: { period },
    });
    return response.data;
  },

  getRotationAnalysis: async (): Promise<RotationAnalysis> => {
    const response = await api.get<RotationAnalysis>(
      "/stats/rotation-analysis",
    );
    return response.data;
  },

  getSmartAlerts: async (): Promise<SmartAlerts> => {
    const response = await api.get<SmartAlerts>("/stats/smart-alerts");
    return response.data;
  },

  getExpenseForecast: async (
    period: "week" | "month" | "quarter" = "month",
  ): Promise<ExpenseForecast> => {
    const response = await api.get<ExpenseForecast>("/stats/expense-forecast", {
      params: { period },
    });
    return response.data;
  },

  getPurchasePatterns: async (): Promise<PurchasePatterns> => {
    const response = await api.get<PurchasePatterns>(
      "/stats/purchase-patterns",
    );
    return response.data;
  },

  getReconciliation: async (): Promise<Reconciliation> => {
    const response = await api.get<Reconciliation>("/stats/reconciliation");
    return response.data;
  },
};
