import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { CategoryAvatar } from "@/components/ui/CategoryAvatar";
import type { StorageStats, CategoryStats } from "@/types";
import { TranslateFn } from "@/types/i18n";
import { categoryLabel } from "@/lib/i18nHelpers";
import { useMoney } from "@/hooks/useMoney";

type Props = {
  t: TranslateFn;
  storageStats: StorageStats[];
  maxStorageCount: number;
  categoryStats: CategoryStats[];
  maxCategoryCount: number;
  /**
   * Whether this profile shows stock value at all — the home profile presets
   * it off, and every money figure on the grid goes with it.
   */
  showInventoryValue?: boolean;
};

export function StatsDistributionGrid({
  t,
  storageStats,
  maxStorageCount,
  categoryStats,
  maxCategoryCount,
  showInventoryValue = true,
}: Props) {
  const money = useMoney();

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-8">
      <Card className="p-4 sm:p-8 border border-transparent">
        <h2 className="text-sm font-semibold text-on-muted uppercase tracking-wide mb-4 sm:mb-8 ml-1">
          {t("stats:storageDistribution")}
        </h2>
        {storageStats && storageStats.length > 0 ? (
          <div className="space-y-6">
            {/* Fullest first, so the places that matter lead and the empty
                ones close the list. */}
            {[...storageStats]
              .sort((a, b) => b.items_count - a.items_count)
              .map((stat, idx) => (
                <div
                  key={
                    stat.location_id ||
                    `${stat.location_name || "storage"}-${idx}`
                  }
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-semibold text-on-secondary uppercase tracking-tight">
                      {stat.location_name}
                    </span>
                    <Badge variant="secondary">
                      {t("stats:recordCount", { count: stat.items_count })}
                    </Badge>
                  </div>
                  <div className="w-full bg-surface-raised rounded-full h-2.5 overflow-hidden">
                    <div
                      className="bg-accent-500 h-full rounded-full transition-all duration-1000"
                      style={{
                        width: `${(stat.items_count / maxStorageCount) * 100}%`,
                      }}
                    />
                  </div>
                </div>
              ))}
          </div>
        ) : (
          <p className="text-on-muted text-center py-8 font-medium italic">
            {t("stats:noData")}
          </p>
        )}
      </Card>

      <Card className="p-4 sm:p-8 border border-transparent">
        <h2 className="text-sm font-semibold text-on-muted uppercase tracking-wide mb-4 sm:mb-8 ml-1">
          {t("stats:categoryDistribution")}
        </h2>
        {categoryStats && categoryStats.length > 0 ? (
          <div className="space-y-6">
            {[...categoryStats]
              // Ordering follows the figure the reader can see: the value
              // while money is on, the count the bars are drawn from once
              // it is off — a hidden amount explains nothing on screen.
              .sort((a, b) =>
                showInventoryValue
                  ? b.total_value - a.total_value
                  : b.items_count - a.items_count,
              )
              .map((stat, idx) => (
                <div
                  key={
                    stat.category_id ||
                    `${stat.category_name || "category"}-${idx}`
                  }
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-3">
                      <CategoryAvatar
                        category={{
                          name: categoryLabel(
                            t,
                            stat.category_code,
                            stat.category_name,
                          ),
                          code: stat.category_code ?? null,
                        }}
                        size="sm"
                      />
                      <span className="text-sm font-semibold text-on-secondary uppercase tracking-tight">
                        {categoryLabel(
                          t,
                          stat.category_code,
                          stat.category_name,
                        )}
                      </span>
                    </div>
                    <div className="flex flex-col items-end">
                      {showInventoryValue && (
                        <span className="text-sm font-semibold text-on">
                          {money(stat.total_value ?? 0)}
                        </span>
                      )}
                      <span className="text-[10px] text-on-muted font-medium uppercase">
                        {t("stats:recordCount", { count: stat.items_count })}
                      </span>
                    </div>
                  </div>
                  <div className="w-full bg-surface-raised rounded-full h-2.5 overflow-hidden">
                    <div
                      className="bg-primary-500 h-full rounded-full transition-all duration-1000"
                      style={{
                        width: `${(stat.items_count / maxCategoryCount) * 100}%`,
                      }}
                    />
                  </div>
                </div>
              ))}
          </div>
        ) : (
          <p className="text-on-muted text-center py-8 font-medium italic">
            {t("stats:noData")}
          </p>
        )}
      </Card>
    </div>
  );
}
