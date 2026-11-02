import { TrendingUp, TrendingDown, Minus, PiggyBank } from "lucide-react";
import type { ExpenseForecast } from "@/modules/stats/types/analytics";
import { Card } from "@/components/ui/Card";
import { cn } from "@/lib/utils";
import { useMoney } from "@/hooks/useMoney";
import { formatPercentLocale } from "@/utils/formatters";

interface ExpenseForecastChartProps {
  data: ExpenseForecast;
  t: (key: string, opts?: Record<string, unknown>) => string;
  /**
   * Whether this profile shows stock value at all. Every figure the section
   * offers is money — the prediction, the average behind it and the savings
   * it projects — and the trend and the confidence bar only describe those
   * withheld amounts, so there is no heading to keep over them.
   */
  showInventoryValue?: boolean;
}

export default function ExpenseForecastChart({
  data,
  t,
  showInventoryValue = true,
}: ExpenseForecastChartProps) {
  const money = useMoney();
  if (!showInventoryValue) return null;

  const getTrendIcon = (trend: string) => {
    switch (trend) {
      case "increasing":
        return <TrendingUp className="w-5 h-5 text-on-danger" />;
      case "decreasing":
        return <TrendingDown className="w-5 h-5 text-on-success" />;
      case "stable":
        return (
          <Minus className="w-5 h-5 text-primary-700 dark:text-primary-500" />
        );
      default:
        return null;
    }
  };

  const getTrendColor = (trend: string) => {
    switch (trend) {
      case "increasing":
        return "text-on-danger";
      case "decreasing":
        return "text-on-success";
      case "stable":
        return "text-primary-700 dark:text-primary-500";
      default:
        return "text-on-secondary";
    }
  };

  const periodLabels: Record<string, string> = {
    week: t("dashboard.thisWeek", { ns: "common" }),
    month: t("dashboard.thisMonth", { ns: "common" }),
    quarter: t("stats:analytics.forecast.quarter"),
  };

  // Below the floor the backend predicts nothing, and the three cards would
  // show a zero, the same zero again, and a confidence bar at 0% — three
  // numbers where the honest answer is one sentence. The waste card stays:
  // what was thrown away last month does not depend on how long the account
  // has been open.
  const hasEnoughHistory =
    data.trend !== "no_data" &&
    !(data.weeks_required > 0 && data.weeks_of_data < data.weeks_required);

  if (!hasEnoughHistory) {
    return (
      <div className="space-y-8">
        <Card className="p-8 border border-transparent text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-surface-raised text-on-muted">
            <TrendingUp size={24} />
          </div>
          <p className="font-semibold text-on">
            {t("stats:analytics.forecast.notEnoughData")}
          </p>
          {data.weeks_required > 0 && (
            <p className="mt-1 text-sm text-on-secondary">
              {t("stats:analytics.forecast.dataProgress", {
                have: data.weeks_of_data,
                need: data.weeks_required,
              })}
            </p>
          )}
        </Card>
        {data.waste_reduction_potential > 0 && (
          <Card className="p-6 bg-accent-50 border border-accent-200">
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 bg-accent-100 rounded-lg flex items-center justify-center flex-shrink-0">
                <PiggyBank className="text-on-success" size={24} />
              </div>
              <div className="flex-1">
                <h3 className="font-semibold text-on mb-1">
                  {t("stats:analytics.forecast.wasteReduction")}
                </h3>
                <p className="text-2xl font-semibold text-accent-600">
                  {money(data.waste_reduction_potential ?? 0)}
                </p>
                <p className="text-xs text-on-secondary mt-1">
                  {t("stats:analytics.forecast.wasteReductionHint")}
                </p>
              </div>
            </div>
          </Card>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Main Forecast Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
        <Card className="p-6 border border-transparent">
          <div className="flex flex-col gap-3">
            <div className="w-10 h-10 bg-accent-50 text-on-success dark:bg-accent-500/10 rounded-xl flex items-center justify-center">
              <TrendingUp size={20} />
            </div>
            <div>
              <p className="text-xs font-medium text-on-muted uppercase tracking-widest mb-1">
                {t("stats:analytics.forecast.predicted")}
              </p>
              <p className="text-2xl font-semibold text-on">
                {money(data.predicted_spending ?? 0)}
              </p>
              <p className="text-xs text-on-secondary mt-2">
                {periodLabels[data.forecast_period]}
              </p>
            </div>
          </div>
        </Card>

        <Card className="p-6 border border-transparent">
          <div className="flex flex-col gap-3">
            <div className="w-10 h-10 bg-primary-50 text-primary-700 dark:text-primary-500 dark:bg-primary-500/10 rounded-xl flex items-center justify-center">
              <TrendingUp size={20} />
            </div>
            <div>
              <p className="text-xs font-medium text-on-muted uppercase tracking-widest mb-1">
                {t("stats:analytics.forecast.historical")}
              </p>
              <p className="text-2xl font-semibold text-on">
                {money(data.historical_avg ?? 0)}
              </p>
              <p className="text-xs text-on-secondary mt-2">
                {t("stats:analytics.forecast.monthlyAvg")}
              </p>
            </div>
          </div>
        </Card>

        <Card className="p-6 border border-transparent">
          <div className="flex flex-col gap-3">
            <div
              className={cn(
                "w-10 h-10 rounded-xl flex items-center justify-center",
                data.trend === "increasing"
                  ? "bg-red-50 text-on-danger dark:bg-red-500/10"
                  : data.trend === "decreasing"
                    ? "bg-accent-50 text-on-success dark:bg-accent-500/10"
                    : "bg-primary-50 text-primary-700 dark:text-primary-500 dark:bg-primary-500/10",
              )}
            >
              {getTrendIcon(data.trend)}
            </div>
            <div>
              <p className="text-xs font-medium text-on-muted uppercase tracking-widest mb-1">
                {t("stats:analytics.forecast.trend")}
              </p>
              <p
                className={cn(
                  "text-xl font-semibold",
                  getTrendColor(data.trend),
                )}
              >
                {t(`stats:analytics.forecast.trends.${data.trend}`)}
              </p>
            </div>
          </div>
        </Card>
      </div>

      {/* Waste Reduction Potential */}
      {data.waste_reduction_potential > 0 && (
        <Card className="p-6 bg-accent-50 border border-accent-200">
          <div className="flex items-start gap-4">
            <div className="w-12 h-12 bg-accent-100 rounded-lg flex items-center justify-center flex-shrink-0">
              <PiggyBank className="text-accent-600" size={24} />
            </div>
            <div className="flex-1">
              <h3 className="font-semibold text-on mb-1">
                {t("stats:analytics.forecast.wasteReduction")}
              </h3>
              <p className="text-2xl font-semibold text-accent-600">
                {money(data.waste_reduction_potential ?? 0)}
              </p>
              <p className="text-xs text-on-secondary mt-1">
                {t("stats:analytics.forecast.wasteReductionHint")}
              </p>
            </div>
          </div>
        </Card>
      )}

      {/* Confidence Indicator */}
      <Card className="p-4 bg-primary-50 border border-primary-200">
        <div className="flex items-center justify-between">
          <p className="text-sm text-on-secondary font-medium">
            {t("stats:analytics.forecast.confidence")}
          </p>
          <div className="flex items-center gap-2">
            <div className="flex-1 w-24 bg-surface-card rounded-full h-2 border border-primary-200">
              <div
                className="bg-primary-500 h-full rounded-full transition-all"
                style={{ width: `${data.confidence * 100}%` }}
              />
            </div>
            <span className="text-sm font-semibold text-primary-700 dark:text-primary-500 w-8 text-right tabular-nums">
              {formatPercentLocale((data.confidence ?? 0) * 100, 0)}
            </span>
          </div>
        </div>
      </Card>
    </div>
  );
}
