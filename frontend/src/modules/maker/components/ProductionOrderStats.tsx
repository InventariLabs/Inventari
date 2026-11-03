import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import {
  Scale,
  TrendingUp,
  AlertTriangle,
  Coins,
  Calendar,
} from "lucide-react";
import { Card } from "@/components/ui/Card";
import { formatMoney } from "@/utils/formatters";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { formatDate, formatDateTime } from "@/utils/helpers";
import type { ProductionOrder } from "@/modules/maker/types/maker";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { useResultTerms } from "@/modules/maker/hooks/useResultTerms";
import { CostFigure } from "@/modules/maker/components/CostFigure";

interface ProductionOrderStatsProps {
  order: ProductionOrder;
}

/**
 * One "label / big value / optional note" tile.
 *
 * Six of these were copy-pasted in this file, differing only in label, value,
 * icon, tone and an optional note. Kept local rather than promoted to
 * `components/ui`: `StatsOverviewCards` looks like the same idea but is a
 * structurally different component (an icon chip beside the value), so a
 * shared one would need a layout variant per caller to say less than the
 * markup does.
 */
function StatTile({
  label,
  children,
  icon,
  valueClass = "text-on",
  valueSize = "text-2xl",
  note,
  className,
}: {
  label: string;
  children: React.ReactNode;
  icon?: React.ReactNode;
  valueClass?: string;
  valueSize?: string;
  note?: React.ReactNode;
  className?: string;
}) {
  return (
    <Card className={`p-4${className ? ` ${className}` : ""}`}>
      <div className="text-xs uppercase tracking-widest text-on-muted font-medium">
        {label}
      </div>
      <div
        className={`${valueSize} font-semibold ${valueClass} mt-1 flex items-center gap-2`}
      >
        {icon}
        {children}
      </div>
      {note ? <div className="text-xs text-on-muted mt-0.5">{note}</div> : null}
    </Card>
  );
}

/** What the cost tile is called: an undone run took nothing and cost nothing now. */
function totalCostLabel(status: string, t: TFunction): string {
  if (status === "DRAFT") {
    return t("detail.card.totalCostAfterClosing", {
      defaultValue: "Total cost after closing",
    });
  }
  if (status === "REVERSED") {
    return t("detail.card.totalCostUndone", {
      defaultValue: "Cost before the run was undone",
    });
  }
  return t("detail.card.totalCost", { defaultValue: "Total cost" });
}

export function ProductionOrderStats({ order }: ProductionOrderStatsProps) {
  const { t, i18n } = useTranslation("maker");
  const resultTerm = useResultTerms();
  const currency = useOrganizationCurrency();

  // Backend stores the overproduction delta as a negative number; the card
  // always shows it as a positive "+N" delta.
  const scrapQty =
    order.scrap_qty === null || order.scrap_qty === undefined
      ? null
      : Math.abs(Number(order.scrap_qty));

  // A line whose consumed stock carried no cost adds nothing to the total,
  // so a closed run's figure is a floor until the page says which lines it
  // leaves out. A draft has consumed nothing, so it has nothing to count.
  const closedLines = order.status === "DRAFT" ? [] : (order.lines ?? []);
  const unpricedLines = closedLines.filter(
    (line) => line.unit_cost_snapshot === null,
  );
  const unpriced = unpricedLines.length;
  // A total above zero with no priced ingredient was built from the run's
  // other costs (labour, overhead): the figure is still a number worth
  // showing, so it must not be treated as a sum with nothing in it.
  const hasOtherCosts = Number(order.total_cost) > 0;
  const priced = Math.max(closedLines.length - unpriced, hasOtherCosts ? 1 : 0);
  const gapId = "production-total-gap";
  const costNote =
    closedLines.length > 0 && (order.unit_cost != null || unpriced > 0) ? (
      <>
        {order.unit_cost != null && (
          <span className="block">
            {t("detail.card.unitCost", {
              amount: formatMoney(order.unit_cost, currency, i18n.language),
            })}
          </span>
        )}
        {unpriced > 0 && (
          <span id={gapId} className="block text-amber-700 dark:text-amber-400">
            {t("detail.card.totalCostGap", {
              count: unpriced,
              names: unpricedLines
                .map((line) => line.child_template_name)
                .filter(Boolean)
                .join(", "),
            })}
          </span>
        )}
      </>
    ) : undefined;

  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatTile
          label={totalCostLabel(order.status, t)}
          icon={<Coins size={18} />}
          note={costNote}
        >
          {closedLines.length > 0 ? (
            <CostFigure
              value={order.total_cost ?? null}
              priced={priced}
              unpriced={unpriced}
              announce={false}
              describedBy={gapId}
            />
          ) : (
            formatMoney(order.total_cost, currency, i18n.language)
          )}
        </StatTile>
        <StatTile
          label={t("detail.card.created", { defaultValue: "Created" })}
          icon={<Calendar size={14} />}
          valueSize="text-base"
          valueClass="text-on font-medium"
        >
          {formatDateTime(order.created_at)}
        </StatTile>
        <StatTile
          label={t("detail.card.productionDate", {
            defaultValue: "Production date",
          })}
          valueSize="text-base"
          valueClass="text-on font-medium"
        >
          {order.production_date ? formatDate(order.production_date) : "—"}
        </StatTile>
      </div>

      {/* Actual / scrap / overproduced stats (completed orders only) */}
      {order.status === "COMPLETED" && order.actual_qty && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <StatTile
            label={t("detail.card.actualQty", {
              defaultValue: "Actual output",
            })}
            icon={<Scale size={18} />}
            note={t("detail.card.plannedSuffix", {
              defaultValue: "planned: {{qty}}",
              qty: formatQuantityLocalized(
                t,
                order.planned_qty,
                order.output_uom_symbol,
              ),
            })}
          >
            {formatQuantityLocalized(
              t,
              order.actual_qty,
              order.output_uom_symbol,
            )}
          </StatTile>
          {/* Financial result snapshot (per-unit × actual output). */}
          {order.result_per_unit !== null &&
            order.result_per_unit !== undefined && (
              <StatTile
                label={resultTerm.label}
                icon={<TrendingUp size={18} />}
                valueClass={
                  Number(order.result_per_unit) >= 0
                    ? "text-accent-600"
                    : "text-red-500"
                }
                note={`${resultTerm.definition} ${t(
                  "detail.card.resultPerUnit",
                  {
                    defaultValue: "({{amount}} per {{unit}})",
                    unit:
                      order.output_uom_symbol || t("create.needs.unitFallback"),
                    amount: formatMoney(
                      order.result_per_unit,
                      currency,
                      i18n.language,
                    ),
                  },
                )}`}
              >
                {formatMoney(
                  Number(order.result_per_unit) * Number(order.actual_qty),
                  currency,
                  i18n.language,
                )}
              </StatTile>
            )}
          {order.overproduced ? (
            <StatTile
              label={t("detail.card.overproduced", {
                defaultValue: "Overproduced",
              })}
              icon={<TrendingUp size={18} />}
              valueClass="text-accent-600"
              className="border-accent-200 bg-accent-50/50"
            >
              {scrapQty !== null && !Number.isNaN(scrapQty)
                ? `+${formatQuantityLocalized(t, scrapQty, order.output_uom_symbol)}`
                : "—"}
            </StatTile>
          ) : (
            order.scrap_qty &&
            Number(order.scrap_qty) > 0 && (
              <StatTile
                label={t("detail.card.scrap", { defaultValue: "Scrap" })}
                icon={<AlertTriangle size={18} />}
                valueClass="text-amber-600"
                className="border-amber-200 bg-amber-50/50"
              >
                {formatQuantityLocalized(
                  t,
                  order.scrap_qty,
                  order.output_uom_symbol,
                )}
              </StatTile>
            )
          )}
        </div>
      )}
    </>
  );
}
