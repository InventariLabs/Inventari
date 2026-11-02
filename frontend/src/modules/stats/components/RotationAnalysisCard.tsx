import { TrendingDown, AlertCircle, Package } from "lucide-react";
import type { RotationAnalysis } from "@/modules/stats/types/analytics";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/utils";
import { useMoney } from "@/hooks/useMoney";
import { categoryLabel } from "@/lib/i18nHelpers";
import { formatNumberLocale } from "@/utils/formatters";

interface RotationAnalysisCardProps {
  data: RotationAnalysis;
  t: (key: string, opts?: Record<string, unknown>) => string;
  /**
   * Whether this profile shows stock value at all. The age tiles and the
   * two lists answer how long stock stands, not what it is worth; only the
   * dead-stock figure is money and goes with the setting.
   */
  showInventoryValue?: boolean;
}

export default function RotationAnalysisCard({
  data,
  t,
  showInventoryValue = true,
}: RotationAnalysisCardProps) {
  const money = useMoney();

  // The age of standing stock does not depend on anything having been
  // consumed — an intake-only organization, i.e. everyone's first days,
  // has a real, computable age, and the category table below reads it from
  // the same payload. "—" is what the server's null means: nothing
  // measurable stands on any shelf. Zero consumption was never a reason to
  // hide a number that was computed and sent.
  const rotationDays = (value: number | null | undefined) =>
    formatNumberLocale(value, 1);

  return (
    <div className="space-y-8">
      {/* Summary Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Card className="p-5 border border-transparent">
          <div className="flex flex-col items-center text-center gap-3">
            <div className="w-10 h-10 bg-primary-50 text-primary-600 rounded-xl flex items-center justify-center">
              <Package size={20} />
            </div>
            <div>
              <p className="text-lg font-semibold text-on leading-none">
                {rotationDays(data.average_stock_age_days)}{" "}
                {data.average_stock_age_days != null && (
                  <span className="text-xs font-normal text-on-secondary">
                    {t("stats:analytics.rotation.days")}
                  </span>
                )}
              </p>
              <p className="text-[10px] font-medium text-on-muted uppercase tracking-widest mt-1">
                {t("stats:analytics.rotation.avgRotation")}
              </p>
            </div>
          </div>
        </Card>

        <Card className="p-5 border border-transparent">
          <div className="flex flex-col items-center text-center gap-3">
            <div className="w-10 h-10 bg-purple-50 text-purple-600 rounded-xl flex items-center justify-center">
              <TrendingDown size={20} />
            </div>
            <div>
              <p className="text-lg font-semibold text-on leading-none">
                {rotationDays(data.median_stock_age_days)}{" "}
                {data.median_stock_age_days != null && (
                  <span className="text-xs font-normal text-on-secondary">
                    {t("stats:analytics.rotation.days")}
                  </span>
                )}
              </p>
              <p className="text-[10px] font-medium text-on-muted uppercase tracking-widest mt-1">
                {t("stats:analytics.rotation.medianRotation")}
              </p>
            </div>
          </div>
        </Card>

        <Card className="p-5 border border-transparent">
          <div className="flex flex-col items-center text-center gap-3">
            <div className="w-10 h-10 bg-amber-50 text-on-warning rounded-xl flex items-center justify-center">
              <AlertCircle size={20} />
            </div>
            <div>
              <p className="text-lg font-semibold text-on leading-none">
                {data.slow_movers_count}
              </p>
              <p className="text-[10px] font-medium text-on-muted uppercase tracking-widest mt-1">
                {t("stats:analytics.rotation.slowMovers")}
              </p>
            </div>
          </div>
        </Card>

        <Card className="p-5 border border-transparent">
          <div className="flex flex-col items-center text-center gap-3">
            <div className="w-10 h-10 bg-red-50 text-on-danger rounded-xl flex items-center justify-center">
              <TrendingDown size={20} />
            </div>
            <div>
              <p className="text-lg font-semibold text-on leading-none">
                {data.dead_stock_count}
              </p>
              <p className="text-[10px] font-medium text-on-muted uppercase tracking-widest mt-1">
                {t("stats:analytics.rotation.deadStock")}
              </p>
            </div>
          </div>
        </Card>
      </div>

      {/* Dead Stock Value */}
      {showInventoryValue &&
        data.dead_stock_value != null &&
        data.dead_stock_value > 0 && (
          <Card className="p-6 bg-red-50 border border-red-200 dark:bg-red-500/10 dark:border-red-500/20">
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 bg-red-100 dark:bg-red-500/10 rounded-lg flex items-center justify-center flex-shrink-0">
                <AlertCircle className="text-on-danger" size={24} />
              </div>
              <div>
                <h3 className="font-semibold text-on mb-1">
                  {t("stats:analytics.rotation.deadStockValue")}
                </h3>
                <p className="text-2xl font-semibold text-on-danger">
                  {money(data.dead_stock_value ?? 0)}
                </p>
              </div>
            </div>
          </Card>
        )}

      {/* Category Breakdown */}
      {data.rotation_by_category && data.rotation_by_category.length > 0 && (
        <Card className="p-6 border border-transparent">
          <h3 className="text-sm font-semibold text-on-muted uppercase tracking-[0.2em] mb-6 ml-1">
            {t("stats:analytics.rotation.byCategory")}
          </h3>
          <div className="space-y-4">
            {data.rotation_by_category.map((cat, idx) => (
              <div key={idx}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-on-secondary">
                    {categoryLabel(t, cat.category_code, cat.category_name)}
                  </span>
                  <div className="flex items-center gap-3">
                    <Badge variant="secondary">{cat.item_count}</Badge>
                    <span className="text-sm font-semibold text-on-secondary">
                      {cat.average_days == null ? (
                        // Null is the server saying there is nothing
                        // measurable for this category. Zero is a true age —
                        // stock taken in today — and the tiles two hundred
                        // pixels up print it as a number; the table says the
                        // same thing about the same payload.
                        t("stats:analytics.rotation.noMovement")
                      ) : (
                        <>
                          {formatNumberLocale(cat.average_days, 1)}{" "}
                          {t("stats:analytics.rotation.days")}
                        </>
                      )}
                    </span>
                  </div>
                </div>
                <div className="w-full bg-surface-raised rounded-full h-2.5">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all",
                      (cat.average_days ?? 0) < 30
                        ? "bg-accent-500"
                        : (cat.average_days ?? 0) < 60
                          ? "bg-amber-500"
                          : "bg-red-500",
                    )}
                    style={{
                      width: `${Math.min(((cat.average_days ?? 0) / 90) * 100, 100)}%`,
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Slow Movers List */}
      {data.slow_movers && data.slow_movers.length > 0 && (
        <Card className="p-6 border border-transparent">
          <h3 className="text-sm font-semibold text-on-muted uppercase tracking-[0.2em] mb-4 ml-1">
            {t("stats:analytics.rotation.slowMovers")}
          </h3>
          <div className="space-y-3">
            {data.slow_movers.slice(0, 10).map((item, idx) => (
              <div
                key={idx}
                className="p-3 bg-amber-50 border border-amber-200 dark:bg-amber-500/10 dark:border-amber-500/20 rounded-lg flex items-center justify-between"
              >
                <div>
                  <p className="font-medium text-on">{item.name}</p>
                  {item.category && (
                    <p className="text-xs text-on-secondary">
                      {categoryLabel(t, item.category_code, item.category)}
                    </p>
                  )}
                </div>
                <span className="text-sm font-semibold text-on-warning whitespace-nowrap ml-4">
                  {item.days_in_storage} {t("stats:analytics.rotation.days")}
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Dead Stock List */}
      {data.dead_stock && data.dead_stock.length > 0 && (
        <Card className="p-6 bg-red-50 border border-red-200">
          <h3 className="text-sm font-semibold text-on uppercase tracking-[0.2em] mb-4 ml-1">
            {t("stats:analytics.rotation.deadStock")}
          </h3>
          <div className="space-y-3">
            {data.dead_stock.slice(0, 10).map((item, idx) => (
              <div
                key={idx}
                className="p-3 bg-surface-card/50 rounded-lg flex items-center justify-between"
              >
                <div>
                  <p className="font-medium text-on">{item.name}</p>
                  {item.category && (
                    <p className="text-xs text-on-secondary">
                      {categoryLabel(t, item.category_code, item.category)}
                    </p>
                  )}
                </div>
                <span className="text-sm font-semibold text-on-danger whitespace-nowrap ml-4">
                  {item.days_in_storage} {t("stats:analytics.rotation.days")}
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
