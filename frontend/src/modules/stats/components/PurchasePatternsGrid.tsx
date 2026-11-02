import { TrendingUp, PiggyBank, Calendar } from "lucide-react";
import type { PurchasePatterns } from "@/modules/stats/types/analytics";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/utils";
import { useMoney } from "@/hooks/useMoney";
import { categoryLabel } from "@/lib/i18nHelpers";
import {
  formatNumberLocale,
  formatPercentLocale,
  formatQuantityValue,
} from "@/utils/formatters";

interface PurchasePatternsGridProps {
  data: PurchasePatterns;
  t: (key: string, opts?: Record<string, unknown>) => string;
  /**
   * Whether this profile shows stock value at all. The pattern rows keep
   * their counts, months and quantities — what recurs and when does not
   * depend on a price — while every money figure goes with the setting.
   */
  showInventoryValue?: boolean;
}

export default function PurchasePatternsGrid({
  data,
  t,
  showInventoryValue = true,
}: PurchasePatternsGridProps) {
  const money = useMoney();

  return (
    <div className="space-y-8">
      {/* Recurring Products */}
      {data.top_recurring_products && data.top_recurring_products.length > 0 ? (
        <Card className="p-6 border border-transparent">
          <h3 className="text-sm font-semibold text-on-muted uppercase tracking-[0.2em] mb-6 ml-1 flex items-center gap-2">
            <TrendingUp size={16} />
            {t("stats:analytics.patterns.recurring")}
          </h3>
          <div className="space-y-4">
            {data.top_recurring_products.map((product, idx) => (
              <div
                key={idx}
                className="p-4 bg-surface rounded-lg border border-border"
              >
                <div className="mb-3 flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold text-on break-words leading-tight">
                      {product.name}
                    </p>
                    {product.brand && (
                      <p className="text-xs text-on-secondary break-words">
                        {product.brand}
                      </p>
                    )}
                    <p className="text-xs text-on-secondary break-words">
                      {categoryLabel(
                        t,
                        product.category_code,
                        product.category,
                      )}
                    </p>
                  </div>
                  <Badge variant="secondary">
                    {product.total_purchases_last_6_months}x
                  </Badge>
                </div>
                {showInventoryValue && (
                  <div className="grid grid-cols-1 gap-3 border-t border-border pt-3 sm:grid-cols-2 sm:gap-4">
                    <div>
                      <p className="mb-1 text-[10px] font-medium leading-tight text-on-muted tracking-wide break-words">
                        {t("common:analytics.patterns.avgPrice")}
                      </p>
                      <p className="text-sm font-semibold text-on">
                        {money(product.avg_price ?? 0)}
                      </p>
                    </div>
                    <div>
                      <p className="mb-1 text-[10px] font-medium leading-tight text-on-muted tracking-wide break-words">
                        {t("common:analytics.patterns.totalSpent")}
                      </p>
                      <p className="text-sm font-semibold text-on">
                        {money(product.total_spent ?? 0)}
                      </p>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      {/* Seasonal Products */}
      {data.seasonal_products && data.seasonal_products.length > 0 ? (
        <Card className="p-6 border border-transparent">
          <h3 className="text-sm font-semibold text-on-muted uppercase tracking-[0.2em] mb-6 ml-1 flex items-center gap-2">
            <Calendar size={16} />
            {t("stats:analytics.patterns.seasonal")}
          </h3>
          <div className="space-y-4">
            {data.seasonal_products.map((product, idx) => (
              <div
                key={idx}
                className="p-4 bg-primary-50 border border-primary-200 dark:bg-primary-500/10 dark:border-primary-500/20 rounded-lg"
              >
                <div className="flex items-start justify-between mb-2">
                  <p className="font-semibold text-on">{product.name}</p>
                  <Badge variant="secondary">
                    {product.seasonality_score == null
                      ? t("stats:analytics.patterns.seasonalityUnknown")
                      : formatPercentLocale(product.seasonality_score * 100, 0)}
                  </Badge>
                </div>
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <p className="text-xs text-on-secondary mb-1">
                      {t("common:analytics.patterns.peakMonth")}
                    </p>
                    <p className="font-semibold text-on">
                      {product.peak_month}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-on-secondary mb-1">
                      {t("common:analytics.patterns.peakQty")}
                    </p>
                    <p className="font-semibold text-on">
                      {formatQuantityValue(product.peak_quantity)}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      {/* Bulk Opportunities */}
      {data.bulk_opportunities && data.bulk_opportunities.length > 0 ? (
        <Card className="p-6 bg-amber-50 border border-amber-200 dark:bg-amber-500/10 dark:border-amber-500/20">
          <h3 className="text-sm font-semibold text-on uppercase tracking-[0.2em] mb-6 ml-1 flex items-center gap-2">
            <PiggyBank size={16} />
            {t("stats:analytics.patterns.bulk")}
          </h3>
          <div className="space-y-4">
            {data.bulk_opportunities.map((opp, idx) => (
              <div key={idx} className="p-4 bg-surface-card/70 rounded-lg">
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <p className="font-semibold text-on">{opp.product}</p>
                    {opp.brand && (
                      <p className="text-xs text-on-secondary">{opp.brand}</p>
                    )}
                  </div>
                </div>
                <div
                  className={cn(
                    "grid grid-cols-2 gap-3 text-sm",
                    showInventoryValue && "sm:grid-cols-3",
                  )}
                >
                  <div>
                    <p className="text-xs text-on-secondary mb-1">
                      {t("common:analytics.patterns.currentPurchase")}
                    </p>
                    <p className="font-semibold text-on">
                      {formatNumberLocale(opp.current_avg_purchase_kg ?? 0, 3)}{" "}
                      kg
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-on-secondary mb-1">
                      {t("common:analytics.patterns.bulkOption")}
                    </p>
                    <p className="font-semibold text-on">
                      {formatNumberLocale(opp.bulk_option_kg ?? 0, 2)} kg
                    </p>
                  </div>
                  {showInventoryValue && (
                    <div>
                      <p className="text-xs text-on-secondary mb-1">
                        {t("common:analytics.patterns.unitPrice")}
                      </p>
                      <p className="font-semibold text-on">
                        {money(opp.unit_price_current ?? 0)}/kg
                      </p>
                    </div>
                  )}
                </div>
                {showInventoryValue && (
                  <div className="mt-3 p-3 bg-accent-50 rounded border border-accent-200 dark:bg-accent-500/10 dark:border-accent-500/20">
                    {/* on-success is the text half of the accent tint pair;
                        accent-600 here measured 3.5:1 at 12px. */}
                    <p className="text-xs text-on-success font-medium">
                      {t("stats:analytics.patterns.potential")}:{" "}
                      <span className="text-on-success">
                        {money(opp.potential_annual_savings ?? 0)}{" "}
                        {t("common:analytics.patterns.perYear")}
                      </span>
                    </p>
                  </div>
                )}
              </div>
            ))}
          </div>
        </Card>
      ) : (
        <Card className="p-8 bg-surface border border-border">
          <p className="text-on-muted text-center font-medium">
            {t("stats:analytics.patterns.noBulk")}
          </p>
        </Card>
      )}
    </div>
  );
}
