import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { TrendingUp, ArrowRight } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { useMakerMonthlyResult } from "@/modules/maker/hooks/useProduction";
import { useResultTerms } from "@/modules/maker/hooks/useResultTerms";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { formatMoney } from "@/utils/formatters";
import { formatMonthName } from "@/utils/helpers";

/**
 * Production's start: the monthly financial result (savings / margin) from
 * completed production order snapshots — one entry per calendar month.
 */
export function MakerResultWidget() {
  const currency = useOrganizationCurrency();
  const { t, i18n } = useTranslation("maker");
  const { data, isLoading } = useMakerMonthlyResult(6);
  const resultTerm = useResultTerms();

  if (isLoading) {
    return (
      <Card className="p-4 animate-pulse">
        <div className="h-4 w-40 rounded bg-surface-inset" />
        <div className="mt-3 h-8 w-24 rounded bg-surface-inset" />
        <div className="mt-3 space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-2.5 w-full rounded bg-surface-inset" />
          ))}
        </div>
      </Card>
    );
  }

  if (!data) return null;

  const months = data.slice().reverse(); // newest first
  const latest = months[0];
  // The service builds six buckets whether or not anything happened in them,
  // "including zero months for chart continuity" — so `months.length` is
  // always six and the empty state it used to guard was unreachable. What
  // makes a month empty is that no run closed in it.
  const hasResults = months.some((month) => month.orders > 0);

  const monthLabel = (month: string) => {
    const [year, m] = month.split("-").map(Number);
    return formatMonthName(year, m);
  };

  /** Green means gained and red means lost; zero means neither. */
  const resultTone = (result: string) => {
    const value = Number(result);
    if (value === 0) return "text-on";
    return value > 0 ? "text-accent-600" : "text-red-500";
  };

  // The name is the production module's own setting, kept on a screen of
  // its own — the definition under the title links back to it, so the word
  // has something to trace it to.
  const definition = (
    <Link
      to="/maker/settings"
      className="underline decoration-dotted underline-offset-2 hover:text-primary-500"
      title={t("widget.hintSource")}
    >
      {resultTerm.definition}
    </Link>
  );

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-on">
            <TrendingUp size={16} className="text-accent-600" />
            {t("widget.title", { result: resultTerm.label })}
          </div>
          <p className="mt-0.5 text-xs text-on-secondary">{definition}</p>
        </div>
        <Link
          to="/maker/production"
          className="flex shrink-0 items-center gap-1 text-xs text-on-secondary hover:text-primary-500"
        >
          {t("widget.viewAll")}
          <ArrowRight size={12} />
        </Link>
      </div>

      {!hasResults && (
        <p className="text-xs text-on-muted">{t("widget.empty")}</p>
      )}

      {hasResults && latest && (
        <div className="rounded-lg bg-surface-raised border border-border p-3">
          <div className="text-[10px] uppercase tracking-widest text-on-secondary font-medium">
            {monthLabel(latest.month)}
          </div>
          <div
            className={`text-2xl font-semibold mt-0.5 ${resultTone(latest.result)}`}
          >
            {formatMoney(latest.result, currency, i18n.language)}
          </div>
          {latest.orders > 0 && (
            <div className="text-[10px] text-on-secondary mt-0.5">
              {t("widget.orders", { count: latest.orders })}
            </div>
          )}
        </div>
      )}

      {hasResults && (
        <div className="mt-3 space-y-1.5">
          {months.slice(1).map((month) => (
            <div
              key={month.month}
              className="flex items-center justify-between gap-2 text-xs"
            >
              <span className="text-on-muted truncate">
                {monthLabel(month.month)}
              </span>
              <span
                className={`font-medium shrink-0 ${resultTone(month.result)}`}
              >
                {formatMoney(month.result, currency, i18n.language)}
              </span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
