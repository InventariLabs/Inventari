import { Link } from "react-router-dom";
import { AlertTriangle, TrendingDown } from "lucide-react";
import { currencyIcon } from "@/utils/currencyIcon";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { TranslateFn } from "@/types/i18n";
import { useMoney } from "@/hooks/useMoney";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { cn } from "@/lib/utils";

type Props = {
  t: TranslateFn;
  needsAttentionCount: number;
  lowStockCount: number;
  /**
   * What the stock is worth, or `null` when nobody priced anything: the sum
   * of no prices is not zero, and "0.00" read as "worth nothing".
   */
  totalInventoryValue: number | null;
  /**
   * Rows left out of the value because their currency is neither the
   * organization's nor unstated. Two currencies do not add, and dropping
   * them without a word turns "we cannot total this" into a confident sum.
   */
  excludedOtherCurrencyCount?: number;
  /**
   * Receipts on the shelf that were posted at no cost. They add nothing to
   * the value, so the figure beside this count is a lower bound — and the
   * tile says so rather than presenting it as the total.
   */
  unvaluedStockCount?: number;
  /**
   * Records on the shelves with no price, when the value is read off the
   * records. They add nothing to it, so the figure beside them is a lower
   * bound — and the tile says so.
   */
  unpricedItemCount?: number;
  /**
   * Whom the value is about. The cost ledger knows products, not shelves,
   * so a figure read from it is the organization's — the caption says so
   * instead of claiming "all items" over a different population than the
   * counts above it.
   */
  valueScope?: "organization" | "locations";
  showDetails: boolean;
  onToggleDetails: () => void;
  /**
   * Whether the total-value signal renders. The value is a business metric;
   * the home profile presets it off through the stats module's settings
   * (`show_inventory_value`), and an admin can flip it back. The
   * "needs attention" and "running low" signals stay either way — those are
   * the questions a home pantry asks too.
   */
  showInventoryValue?: boolean;
};

export function StatsHealthCard({
  t,
  needsAttentionCount,
  lowStockCount,
  totalInventoryValue,
  excludedOtherCurrencyCount = 0,
  unvaluedStockCount = 0,
  unpricedItemCount = 0,
  valueScope = "locations",
  showDetails,
  onToggleDetails,
  showInventoryValue = true,
}: Props) {
  const money = useMoney();
  const CurrencyIcon = currencyIcon(useOrganizationCurrency());

  // As many tiles as are on screen — the subtitle counts them. The
  // needs-attention tile stopped depending on expiry tracking the moment
  // its number grew to include running low: a workspace with no dates can
  // still have an empty shelf, and a tile that stayed at zero by definition
  // was the old number, not this one.
  const signalCount = 2 + (showInventoryValue ? 1 : 0);

  return (
    <Card className="p-4 sm:p-6 border border-transparent">
      <div className="mb-5">
        <h2 className="text-lg sm:text-xl font-semibold text-on">
          {t("stats:health.title")}
        </h2>
        <p className="text-sm text-on-secondary mt-1">
          {/* As many as are on screen. The sentence said "three" whatever the
              grid showed, and a workspace that keeps no dates showed two. */}
          {t("stats:health.subtitle", { count: signalCount })}
        </p>
      </div>

      <div
        className={cn(
          "grid grid-cols-1 gap-3",
          signalCount === 3 && "sm:grid-cols-3",
          signalCount === 2 && "sm:grid-cols-2",
        )}
      >
        {/* The number is expired + expiring + running low; the products
            list's "needs attention" filter is those records, so the tile
            opens what it counts rather than every record. */}
        <Link to="/inventory/items?filter=needs-attention" className="block">
          {/* Tint + text half of the pair (UI_GUIDELINES §1.1): the wash
              `bg-amber-500/10` with `text-amber-500` measured 1.99:1 —
              the colour on a 10% wash of itself. */}
          <div className="h-full rounded-xl border border-amber-200 bg-amber-50 dark:bg-amber-500/10 dark:border-amber-500/20 p-4 hover:border-amber-500/50 transition-colors">
            <div className="flex items-center gap-2 text-on-warning mb-2">
              <AlertTriangle size={16} />
              <p className="text-xs font-medium uppercase tracking-wide">
                {t("stats:health.needsAttention")}
              </p>
            </div>
            <p className="text-2xl font-semibold text-on-warning leading-none">
              {needsAttentionCount}
            </p>
            <p className="text-xs text-on-warning/90 mt-2">
              {t("stats:health.needsAttentionHint")}
            </p>
          </div>
        </Link>

        <Link to="/inventory/items?filter=low-stock" className="block">
          <div className="h-full rounded-xl border border-primary-200 bg-primary-50 dark:bg-primary-500/10 dark:border-primary-500/20 p-4 hover:border-primary-500/50 transition-colors">
            <div className="flex items-center gap-2 text-primary-700 dark:text-primary-500 mb-2">
              <TrendingDown size={16} />
              <p className="text-xs font-medium uppercase tracking-wide">
                {t("stats:health.runningLow")}
              </p>
            </div>
            <p className="text-2xl font-semibold text-primary-700 dark:text-primary-500 leading-none">
              {lowStockCount}
            </p>
            {/* No opacity de-emphasis on 12px text (UI_GUIDELINES §6):
                /90 measured 4.32:1 light / 4.35:1 dark — under AA. */}
            <p className="text-xs text-primary-700 dark:text-primary-500 mt-2">
              {t("stats:health.runningLowHint")}
            </p>
          </div>
        </Link>

        {/* The value is a business metric read off a cost ledger; the home
            profile presets the signal off through the module's settings, and
            an admin can flip it back. */}
        {showInventoryValue && (
          <div className="rounded-xl border border-accent-200 bg-accent-50 p-4">
            <div className="flex items-center gap-2 text-accent-700 mb-2">
              <CurrencyIcon size={16} />
              <p className="text-xs font-medium uppercase tracking-wide">
                {t("stats:health.totalValue")}
              </p>
            </div>
            <p className="text-2xl font-semibold text-accent-700 leading-none">
              {totalInventoryValue === null
                ? t("stats:health.valueUnknown")
                : money(totalInventoryValue)}
            </p>
            {/* /80 blended the 12px hint to 3.58:1 light / 4.38:1 dark —
                under AA (UI_GUIDELINES §6: no opacity on small text). */}
            <p className="text-xs text-accent-700 mt-2">
              {totalInventoryValue === null
                ? t("stats:health.valueUnknownHint")
                : valueScope === "organization"
                  ? t("stats:health.totalValueHintLedger")
                  : t("stats:health.totalValueHint")}
            </p>
            {totalInventoryValue !== null && unpricedItemCount > 0 && (
              <p className="text-xs text-on-warning mt-2">
                {t("stats:health.unpricedItems", { total: unpricedItemCount })}
              </p>
            )}
            {excludedOtherCurrencyCount > 0 && (
              <p className="text-xs text-on-warning mt-2">
                {t("stats:costAnalysis.excludedOtherCurrency", {
                  count: excludedOtherCurrencyCount,
                })}
              </p>
            )}
            {/* A bound on an unknown value says nothing: "Unknown" already
                says why. */}
            {totalInventoryValue !== null && unvaluedStockCount > 0 && (
              <p className="text-xs text-on-warning mt-2">
                {t("stats:health.unvaluedStock", { total: unvaluedStockCount })}
              </p>
            )}
          </div>
        )}
      </div>

      <div className="mt-4 flex items-center justify-between gap-3">
        <p className="text-xs text-on-secondary">
          {t("stats:health.actionsHint")}
        </p>
        <Button
          type="button"
          onClick={onToggleDetails}
          variant="outline"
          size="contentSm"
          className="shrink-0 px-3 py-2 text-xs font-medium hover:bg-surface"
        >
          {showDetails
            ? t("stats:health.hideDetails")
            : t("stats:health.showDetails")}
        </Button>
      </div>
    </Card>
  );
}
