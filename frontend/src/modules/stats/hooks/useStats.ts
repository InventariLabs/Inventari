import { statsApi } from "@/modules/stats/api/stats";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
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
import { statsConfigApi, type StatsConfig } from "@/lib/api/statsConfig";
import { queryKeys } from "@/hooks/queries/keys";
import { useAttentionCounts } from "@/modules/shared/hooks/useAttentionCounts";

/**
 * Module-level toggles. `enable_analytics` decides whether the
 * analytics tab and its route exist for this organization — the profile
 * presets it (off for food_home), an admin can flip it in module settings.
 */
export function useStatsConfig() {
  return useModuleQuery<StatsConfig>("stats", {
    queryKey: queryKeys.stats.config,
    queryFn: () => statsConfigApi.get(),
  });
}

/**
 * Fetches overview stats.
 * NOTE: Use `queryKeys.stats.overview` = ['stats', 'overview'] as the canonical key.
 * Old code may invalidate ['stats-overview'] — see invalidation.ts for details.
 */
export function useStatsOverview() {
  return useModuleQuery<OverviewStats>("stats", {
    queryKey: queryKeys.stats.overview,
    queryFn: () => statsApi.getOverview(),
  });
}

/**
 * The overview tab's two headline answers as one unit: the overview itself
 * and the one attention count both this tab and the dashboard read.
 *
 * The page shows one spinner until both are in, one failure card when either
 * does not arrive, and one retry that asks both again — that is a property
 * of the pair, so it lives here rather than as three branches around them.
 * Until both answers arrive `data` stays undefined: one half must never
 * stand in for the other with a zero.
 */
export function useStatsHeadline(excludeModuleContexts: boolean) {
  const overview = useStatsOverview();
  const attention = useAttentionCounts(excludeModuleContexts);

  return {
    data:
      overview.data && attention.data
        ? { overview: overview.data, counts: attention.data }
        : undefined,
    isLoading: overview.isLoading || attention.isLoading,
    isError: overview.isError || attention.isError,
    refetch: () => {
      void overview.refetch();
      void attention.refetch();
    },
  };
}

export function useStatsByStorage() {
  return useModuleQuery<StorageStats[]>("stats", {
    queryKey: queryKeys.stats.byStorage,
    queryFn: () => statsApi.getByStorage(),
  });
}

export function useStatsByCategory() {
  return useModuleQuery<CategoryStats[]>("stats", {
    queryKey: queryKeys.stats.byCategory,
    queryFn: () => statsApi.getByCategory(),
  });
}

export function useExpiryForecast() {
  return useModuleQuery<ExpiryForecast[]>("stats", {
    queryKey: queryKeys.stats.expiryForecast,
    queryFn: () => statsApi.getExpiryForecast(),
  });
}

export function useCostAnalysis(period: string = "month") {
  return useModuleQuery<CostAnalysis>("stats", {
    // The period is part of the key: two components asking for different
    // periods must not share one cache entry (whoever mounted first won).
    queryKey: queryKeys.stats.costAnalysis(period),
    queryFn: () => statsApi.getCostAnalysis(period),
  });
}

export function useRotationAnalysis(enabled = true) {
  return useModuleQuery<RotationAnalysis>("stats", {
    queryKey: queryKeys.stats.rotationAnalysis,
    queryFn: () => statsApi.getRotationAnalysis(),
    extraEnabled: enabled,
  });
}

export function useSmartAlerts(enabled = true) {
  return useModuleQuery<SmartAlerts>("stats", {
    queryKey: queryKeys.stats.smartAlerts,
    queryFn: () => statsApi.getSmartAlerts(),
    extraEnabled: enabled,
  });
}

export function useExpenseForecast(
  enabled = true,
  period: "week" | "month" | "quarter" = "month",
) {
  return useModuleQuery<ExpenseForecast>("stats", {
    // Period in the key, enabled as its own parameter — overloading the
    // period position with a boolean flag made both unreadable.
    queryKey: queryKeys.stats.expenseForecast(period),
    queryFn: () => statsApi.getExpenseForecast(period),
    extraEnabled: enabled,
  });
}

export function usePurchasePatterns(enabled = true) {
  return useModuleQuery<PurchasePatterns>("stats", {
    queryKey: queryKeys.stats.purchasePatterns,
    queryFn: () => statsApi.getPurchasePatterns(),
    extraEnabled: enabled,
  });
}

/**
 * The three pair comparisons behind the drift warning admins receive.
 *
 * Deliberately not cached beyond the default: a figure whose whole job is to
 * say whether two records still agree is worth nothing if it is stale.
 */
export function useReconciliation(enabled = true) {
  return useModuleQuery<Reconciliation>("stats", {
    queryKey: queryKeys.stats.reconciliation,
    queryFn: () => statsApi.getReconciliation(),
    extraEnabled: enabled,
  });
}
