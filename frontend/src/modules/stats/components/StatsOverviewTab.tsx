import type {
  AttentionCounts,
  OverviewStats,
  StorageStats,
  CategoryStats,
  ExpiryForecast,
} from "@/types";
import type { CostAnalysis } from "@/modules/stats/types/analytics";
import { TranslateFn } from "@/types/i18n";
import { attentionCount } from "@/modules/shared/hooks/useAttentionCounts";
import { StatsHealthCard } from "./StatsHealthCard";
import { StatsOverviewCards } from "./StatsOverviewCards";
import { StatsDistributionGrid } from "./StatsDistributionGrid";
import { StatsExpiryForecast } from "./StatsExpiryForecast";
import { StatsCostAnalysis } from "./StatsCostAnalysis";
import { QueryFailure } from "@/components/ui/QueryResult";

/**
 * One of the tab's sections whose numbers did not arrive.
 *
 * The page used to gate its whole body on the cost query having succeeded,
 * so a single failing request left the reader with a header, two tabs and
 * nothing else -- no message, no retry, and no sign that the four sections
 * which did arrive existed at all. A section that failed says so and offers
 * the one action that can change it; the rest of the tab renders.
 */
export type StatsSectionFailure = {
  key: string;
  message: string;
  error: unknown;
  onRetry: () => void;
};

type Props = {
  t: TranslateFn;
  overview: OverviewStats;
  /** The three attention shares, from the one endpoint both screens read. */
  attentionCounts: AttentionCounts;
  storageStats: StorageStats[];
  categoryStats: CategoryStats[];
  expiryForecast: ExpiryForecast[];
  costAnalysis: CostAnalysis | undefined;
  failures: StatsSectionFailure[];
  showDetails: boolean;
  onToggleDetails: () => void;
  tracksExpiry: boolean;
  /**
   * Whether the total-value signal is on for this organization. The value is
   * a business metric; the home profile presets it off through the module's
   * settings, and an admin can flip it back.
   */
  showInventoryValue: boolean;
};

export default function StatsOverviewTab({
  t,
  overview,
  attentionCounts,
  storageStats,
  categoryStats,
  expiryForecast,
  costAnalysis,
  failures,
  showDetails,
  onToggleDetails,
  tracksExpiry,
  showInventoryValue,
}: Props) {
  const maxStorageCount = Math.max(
    ...(storageStats?.map((s) => s.items_count) || [1]),
  );
  const maxCategoryCount = Math.max(
    ...(categoryStats?.map((c) => c.items_count) || [1]),
  );
  // From the overview, which sums it over the items. Summing the per-category
  // subtotals put "$0.00" on a warehouse of ninety priced products the moment
  // none of them had a category — the state right after an import, and exactly
  // when somebody asks what the stock is worth for the first time.
  // "Nobody priced anything" is unknown, not zero.
  const totalInventoryValue =
    overview?.value_known === false ? null : Number(overview?.total_value) || 0;
  // One source for the count, shared with the dashboard's attention card:
  // expired, expiring soon, or running low, where "running low" is the
  // product-level rule. Computing it here from the overview made this tile
  // read a different number than the dashboard on the very same data; the
  // two screens now read the one endpoint (see `useAttentionCounts`).
  const needsAttentionCount = attentionCount(attentionCounts);

  return (
    <div className="space-y-10">
      <StatsHealthCard
        t={t}
        showInventoryValue={showInventoryValue}
        needsAttentionCount={needsAttentionCount}
        lowStockCount={attentionCounts.low_stock}
        totalInventoryValue={totalInventoryValue}
        excludedOtherCurrencyCount={
          overview?.excluded_other_currency_count ?? 0
        }
        unvaluedStockCount={overview?.unvalued_stock_count ?? 0}
        unpricedItemCount={overview?.unpriced_item_count ?? 0}
        valueScope={
          overview?.value_scope === "organization"
            ? "organization"
            : "locations"
        }
        showDetails={showDetails}
        onToggleDetails={onToggleDetails}
      />

      {showDetails && (
        <>
          {failures.map((failure) => (
            <QueryFailure
              key={failure.key}
              error={failure.error}
              message={failure.message}
              onRetry={failure.onRetry}
            />
          ))}

          <StatsOverviewCards
            t={t}
            overview={overview}
            attentionCounts={attentionCounts}
            tracksExpiry={tracksExpiry}
          />

          <StatsDistributionGrid
            t={t}
            storageStats={storageStats}
            maxStorageCount={maxStorageCount}
            categoryStats={categoryStats}
            maxCategoryCount={maxCategoryCount}
            showInventoryValue={showInventoryValue}
          />

          <StatsExpiryForecast t={t} expiryForecast={expiryForecast} />

          {costAnalysis && (
            <StatsCostAnalysis
              t={t}
              costAnalysis={costAnalysis}
              showInventoryValue={showInventoryValue}
            />
          )}
        </>
      )}
    </div>
  );
}
