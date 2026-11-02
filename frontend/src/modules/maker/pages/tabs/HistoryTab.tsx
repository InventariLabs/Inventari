import { useId } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { ChevronRight, History } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { QueryError } from "@/components/ui/QueryResult";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { useProductionOrders } from "@/modules/maker/hooks/useProduction";
import { ProductionStatusBadge } from "@/modules/maker/components/ProductionStatusBadge";
import type { MakerRecipe } from "@/modules/maker/types/maker";
import { formatDate } from "@/utils/helpers";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { formatMoney } from "@/utils/formatters";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { useResultTerms } from "@/modules/maker/hooks/useResultTerms";

interface HistoryTabProps {
  recipe: MakerRecipe;
}

/**
 * Past production runs for this formula.
 *
 * Each run used to be three lines of prose stacked at `mt-0.5` inside one
 * button — date, quantities and money all competing at the same size. It is
 * a record list, so it is a table (UI_GUIDELINES §14.1) with one column per
 * question: when, what state, how much was made, what it cost, what it
 * returned. Phones get the same fields as stacked cards.
 */
export function HistoryTab({ recipe }: HistoryTabProps) {
  const currency = useOrganizationCurrency();
  const { t, i18n } = useTranslation("maker");
  const resultTerm = useResultTerms();
  const resultDefinitionId = useId();
  const navigate = useNavigate();

  const { data, isLoading, isError, refetch } = useProductionOrders({
    output_template_id: recipe.output_template_id,
    limit: 50,
  });

  const orders = data?.items ?? [];
  const money = (value: string | number | null | undefined) =>
    value === null || value === undefined
      ? "—"
      : formatMoney(value, currency, i18n.language);

  if (isLoading) {
    return (
      <Card className="p-4">
        <p className="text-center py-8 text-on-muted text-sm">
          {t("detail.loading")}
        </p>
      </Card>
    );
  }

  // "No runs yet" is a statement about the recipe; a failed read says nothing.
  if (isError) {
    return (
      <Card className="p-4">
        <QueryError onRetry={() => void refetch()} />
      </Card>
    );
  }

  if (orders.length === 0) {
    return (
      <Card className="p-4">
        <EmptyState
          icon={History}
          title={t("detail.history.title")}
          description={t("detail.history.empty")}
          variant="compact"
        />
      </Card>
    );
  }

  return (
    <Card className="p-4 space-y-3">
      <h3 className="text-xs uppercase tracking-widest text-on-muted font-medium">
        {t("detail.history.title")}
      </h3>
      {/* Above both layouts, so the phone's cards have it too; a header's
          hover title never reached a finger. */}
      <p id={resultDefinitionId} className="text-xs text-on-muted">
        {resultTerm.label}: {resultTerm.definition}
      </p>

      {/* Desktop: one row per run, one column per question. */}
      <div className="relative hidden sm:block overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs uppercase tracking-wide text-on-muted">
              <th scope="col" className="text-left font-medium py-2 pr-3">
                {t("detail.history.date")}
              </th>
              <th scope="col" className="text-left font-medium py-2 pr-3">
                {t("detail.history.status")}
              </th>
              <th scope="col" className="text-right font-medium py-2 pr-3">
                {t("detail.history.made")}
              </th>
              <th scope="col" className="text-right font-medium py-2 pr-3">
                {t("detail.history.unitCostColumn")}
              </th>
              <th
                scope="col"
                className="text-right font-medium py-2 pr-3"
                aria-describedby={resultDefinitionId}
              >
                {t("detail.history.resultColumn", { result: resultTerm.label })}
              </th>
              <th scope="col" className="text-right font-medium py-2 pr-3">
                {t("detail.history.totalColumn")}
              </th>
              <th scope="col" className="w-8">
                <span className="sr-only">{t("detail.history.open")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {orders.map((order) => (
              <tr
                key={order.id}
                className="border-t border-border/60 hover:bg-surface-raised/40"
              >
                <td className="py-2.5 pr-3 text-on-muted whitespace-nowrap">
                  {formatDate(order.completed_at ?? order.created_at)}
                </td>
                <td className="py-2.5 pr-3">
                  <ProductionStatusBadge status={order.status} />
                </td>
                <td className="py-2.5 pr-3 text-right font-medium text-on tabular-nums">
                  {formatQuantityLocalized(
                    t,
                    order.actual_qty ?? order.planned_qty,
                    order.output_uom_symbol,
                  )}
                  {order.actual_qty !== null &&
                    order.actual_qty !== order.planned_qty && (
                      <span className="text-xs text-on-muted font-normal">
                        {" "}
                        {t("detail.card.plannedSuffix", {
                          qty: formatQuantityLocalized(
                            t,
                            order.planned_qty,
                            order.output_uom_symbol,
                          ),
                        })}
                      </span>
                    )}
                </td>
                <td className="py-2.5 pr-3 text-right text-on-muted tabular-nums">
                  {money(order.unit_cost_snapshot)}
                </td>
                <td
                  className={`py-2.5 pr-3 text-right tabular-nums ${
                    order.result_per_unit !== null &&
                    Number(order.result_per_unit) < 0
                      ? "text-red-500"
                      : "text-accent-600"
                  }`}
                >
                  {money(order.result_per_unit)}
                </td>
                <td className="py-2.5 pr-3 text-right font-medium text-on tabular-nums">
                  {money(order.total_cost)}
                </td>
                <td className="py-2.5 text-right">
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => navigate(`/maker/production/${order.id}`)}
                    aria-label={t("detail.history.open")}
                  >
                    <ChevronRight size={16} className="text-on-muted" />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Phone: the same fields, stacked. */}
      <div className="space-y-2 sm:hidden">
        {orders.map((order) => (
          <Button
            size="content"
            key={order.id}
            variant="ghost"
            className="w-full flex flex-col items-stretch gap-2 px-3 py-3 rounded-lg bg-surface-raised/40 border border-border/60 text-left"
            onClick={() => navigate(`/maker/production/${order.id}`)}
          >
            <span className="flex items-center justify-between gap-2">
              <ProductionStatusBadge status={order.status} />
              <span className="text-xs text-on-muted">
                {formatDate(order.completed_at ?? order.created_at)}
              </span>
            </span>
            <span className="flex items-center justify-between gap-2">
              <span className="text-xs text-on-muted">
                {t("detail.history.made")}
              </span>
              <span className="text-sm font-medium text-on tabular-nums">
                {formatQuantityLocalized(
                  t,
                  order.actual_qty ?? order.planned_qty,
                  order.output_uom_symbol,
                )}
              </span>
            </span>
            <span className="flex items-center justify-between gap-2">
              <span className="text-xs text-on-muted">
                {t("detail.history.unitCostColumn")}
              </span>
              <span className="text-sm text-on tabular-nums">
                {money(order.unit_cost_snapshot)}
              </span>
            </span>
            {order.result_per_unit !== null && (
              <span className="flex items-center justify-between gap-2">
                <span className="text-xs text-on-muted">
                  {t("detail.history.resultColumn", {
                    result: resultTerm.label,
                  })}
                </span>
                <span
                  className={`text-sm font-medium tabular-nums ${
                    Number(order.result_per_unit) < 0
                      ? "text-red-500"
                      : "text-accent-600"
                  }`}
                >
                  {money(order.result_per_unit)}
                </span>
              </span>
            )}
          </Button>
        ))}
      </div>
    </Card>
  );
}
