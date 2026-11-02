import {
  DollarSign,
  TrendingDown,
  AlertTriangle,
  TrendingUp,
  PiggyBank,
} from "lucide-react";
import { Card } from "@/components/ui/Card";
import type {
  CostAnalysis,
  CategoryCostItem,
  MonthlyTrendItem,
  SavingsOpportunity,
} from "@/modules/stats/types/analytics";
import { TranslateFn } from "@/types/i18n";
import { useMoney } from "@/hooks/useMoney";
import { formatPercentLocale } from "@/utils/formatters";
import { categoryLabel } from "@/lib/i18nHelpers";

type Props = {
  t: TranslateFn;
  costAnalysis: CostAnalysis;
  /**
   * Whether this profile shows stock value at all — the home profile presets
   * it off. Every figure below is money, so the section has nothing to say
   * to a profile without the signal: it goes whole.
   */
  showInventoryValue?: boolean;
};

export function StatsCostAnalysis({
  t,
  costAnalysis,
  showInventoryValue = true,
}: Props) {
  const money = useMoney();
  if (!showInventoryValue) return null;
  // Two tiles can be genuinely unanswerable. An outflow is priced when it
  // happens and the ledger keeps that price; for a window from before the
  // ledger kept it there is nothing to read, and today's average was not the
  // average then. Printing 0.00 there would tell the reader they wasted
  // nothing, which is the one thing we know is not true.
  const unknown = "—";
  // The spent total and the category rows are two different sums: the total
  // is read off the valuation ledger, the rows off the purchase price on
  // each record. When a category of priced records sits under a ledger
  // total, its row can honestly read 0.00 — naming the source next to the
  // breakdown is what keeps that from reading as "nothing was spent here".
  // The keys stay inline in the JSX below on purpose: routed through a
  // variable, the i18n gate would count them as orphans it cannot see
  // being used.
  const rowsSource =
    costAnalysis.top_expensive_categories?.[0]?.value_source ?? null;

  return (
    <div className="space-y-10 pt-10 border-t border-border">
      <div className="px-1">
        <h2 className="text-2xl font-semibold text-on leading-none mb-2">
          {t("stats:costAnalysis.title")}
        </h2>
        <p className="text-lg font-semibold text-on-muted">
          {t("stats:costAnalysis.subtitle")}
        </p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Card className="p-6 border border-transparent">
          <div className="flex flex-col items-center text-center gap-3">
            <div className="w-12 h-12 bg-accent-50 text-accent-600 rounded-2xl flex items-center justify-center shadow-sm">
              <DollarSign size={24} strokeWidth={2.5} />
            </div>
            <div>
              <p className="text-xl font-semibold text-on leading-none mb-1">
                {money(costAnalysis.total_spent ?? 0)}
              </p>
              <p className="text-[10px] font-medium text-on-muted uppercase tracking-wide leading-tight">
                {t("stats:costAnalysis.spent")}
              </p>
              {/* Prices in another currency cannot be added to these, and were
                  dropped without a word — so a warehouse of a hundred and fifty
                  priced products reported having spent nothing at all. */}
              {(costAnalysis.excluded_other_currency_count ?? 0) > 0 && (
                <p className="text-[10px] text-amber-600 mt-2 max-w-[16rem]">
                  {t("stats:costAnalysis.excludedOtherCurrency", {
                    count: costAnalysis.excluded_other_currency_count,
                  })}
                </p>
              )}
            </div>
          </div>
        </Card>

        <Card className="p-6 border border-transparent">
          <div className="flex flex-col items-center text-center gap-3">
            <div className="w-12 h-12 bg-red-50 text-red-600 rounded-2xl flex items-center justify-center shadow-sm">
              <TrendingDown size={24} strokeWidth={2.5} />
            </div>
            <div>
              <p className="text-xl font-semibold text-on leading-none mb-1">
                {costAnalysis.total_wasted === null
                  ? unknown
                  : money(costAnalysis.total_wasted)}
              </p>
              <p className="text-[10px] font-medium text-on-muted uppercase tracking-wide leading-tight">
                {t("stats:costAnalysis.wasted")}
              </p>
              {costAnalysis.total_wasted === null && (
                <p className="text-[10px] text-on-muted mt-1 leading-tight">
                  {t("stats:costAnalysis.notValuedYet")}
                </p>
              )}
            </div>
          </div>
        </Card>

        <Card className="p-6 border border-transparent">
          <div className="flex flex-col items-center text-center gap-3">
            <div className="w-12 h-12 bg-amber-50 text-amber-600 rounded-2xl flex items-center justify-center shadow-sm">
              <AlertTriangle size={24} strokeWidth={2.5} />
            </div>
            <div>
              <p className="text-xl font-semibold text-on leading-none mb-1">
                {costAnalysis.waste_value_percentage === null
                  ? unknown
                  : // Off the wire, already rounded to two places; the figure
                    // keeps one decimal and takes the reader's own mark.
                    formatPercentLocale(costAnalysis.waste_value_percentage, 1)}
              </p>
              <p className="text-[10px] font-medium text-on-muted uppercase tracking-wide leading-tight">
                {t("stats:costAnalysis.waste")}
              </p>
            </div>
          </div>
        </Card>

        <Card className="p-6 border border-transparent">
          <div className="flex flex-col items-center text-center gap-3">
            <div className="w-12 h-12 bg-primary-50 text-primary-600 rounded-2xl flex items-center justify-center shadow-sm">
              <PiggyBank size={24} strokeWidth={2.5} />
            </div>
            <div>
              <p className="text-xl font-semibold text-on leading-none mb-1">
                {costAnalysis.savings_opportunities.length}
              </p>
              <p className="text-[10px] font-medium text-on-muted uppercase tracking-wide leading-tight">
                {t("stats:costAnalysis.savings")}
              </p>
            </div>
          </div>
        </Card>
      </div>

      {costAnalysis.top_expensive_categories &&
        costAnalysis.top_expensive_categories.length > 0 && (
          <div className="bg-surface-card rounded-xl p-6 shadow-sm border">
            <h3 className="text-lg font-semibold text-on mb-2">
              {t("stats:costAnalysis.topCategories")}
            </h3>
            {rowsSource === "purchase_price" && (
              <p className="text-xs text-on-secondary mb-4">
                {t("stats:costAnalysis.categoriesPricedFromRecords")}
              </p>
            )}
            {rowsSource === "valuation_layers" && (
              <p className="text-xs text-on-secondary mb-4">
                {t("stats:costAnalysis.categoriesPricedFromLedger")}
              </p>
            )}
            <div className="space-y-4">
              {costAnalysis.top_expensive_categories.map(
                (cat: CategoryCostItem, idx: number) => (
                  <div key={idx}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm font-medium text-on-secondary">
                        {categoryLabel(t, cat.category_code, cat.category_name)}
                      </span>
                      <span className="text-sm text-on-secondary">
                        {money(cat.total_spent ?? 0)}
                      </span>
                    </div>
                    <div className="w-full bg-surface-inset rounded-full h-3">
                      <div
                        className="bg-accent-500 h-3 rounded-full transition-all"
                        style={{
                          width: `${Math.min((cat.total_spent / (costAnalysis.total_spent || 1)) * 100, 100)}%`,
                        }}
                      />
                    </div>
                    {/* The row counts every record in the category, but a
                        record without a purchase price adds zero to the sum:
                        a bare 0.00 over four items would read as "nothing
                        was spent here" rather than "no price to read". */}
                    {(cat.unpriced_count ?? 0) > 0 && (
                      <p className="text-xs text-on-muted mt-1">
                        {t("stats:costAnalysis.categoryUnpriced", {
                          count: cat.unpriced_count,
                        })}
                      </p>
                    )}
                  </div>
                ),
              )}
            </div>
          </div>
        )}

      {costAnalysis.savings_opportunities &&
        costAnalysis.savings_opportunities.length > 0 && (
          <div className="bg-surface-card rounded-xl p-6 shadow-sm border">
            <h3 className="text-lg font-semibold text-on mb-4 flex items-center gap-2">
              <PiggyBank size={20} />
              {t("stats:costAnalysis.savingsOpportunities")}
            </h3>
            <div className="space-y-3">
              {costAnalysis.savings_opportunities.map(
                (opp: SavingsOpportunity, idx: number) => (
                  <div
                    key={idx}
                    className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg"
                  >
                    <div className="flex justify-between items-start mb-2">
                      <div>
                        <p className="font-medium text-on">
                          {opp.product_name}
                        </p>
                        <p className="text-sm text-on-secondary">
                          {categoryLabel(
                            t,
                            opp.category_code,
                            opp.category_name,
                          )}
                        </p>
                      </div>
                      <span className="text-red-600 font-medium">
                        -{money(opp.wasted_amount ?? 0)}
                      </span>
                    </div>
                    <p className="text-sm text-on-secondary">
                      {opp.suggestion}
                    </p>
                  </div>
                ),
              )}
            </div>
          </div>
        )}

      {costAnalysis.monthly_trend && costAnalysis.monthly_trend.length > 0 && (
        <div className="bg-surface-card rounded-xl p-6 shadow-sm border">
          <h3 className="text-lg font-semibold text-on mb-4 flex items-center gap-2">
            <TrendingUp size={20} />
            {t("stats:costAnalysis.monthlyTrend")}
          </h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
            {costAnalysis.monthly_trend.map(
              (month: MonthlyTrendItem, idx: number) => (
                <div
                  key={idx}
                  className="p-3 bg-surface rounded-lg text-center"
                >
                  <p className="text-sm font-medium text-on-secondary">
                    {month.month}
                  </p>
                  <p className="text-lg font-semibold text-accent-600">
                    {money(month.spent ?? 0)}
                  </p>
                  {month.wasted > 0 && (
                    <p className="text-xs text-red-600">
                      -{money(month.wasted ?? 0)}
                    </p>
                  )}
                </div>
              ),
            )}
          </div>
        </div>
      )}
    </div>
  );
}
