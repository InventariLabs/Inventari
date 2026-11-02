import { useId } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { DuplicateOrderButton } from "./DuplicateOrderButton";
import { Card } from "@/components/ui/Card";
import { ProductionShortageSignal } from "@/modules/maker/components/ProductionShortageSignal";
import { ProductionStatusBadge } from "@/modules/maker/components/ProductionStatusBadge";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { formatMoney } from "@/utils/formatters";
import { formatDate } from "@/utils/helpers";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import type { ProductionOrder } from "@/modules/maker/types/maker";
import { useResultTerms } from "@/modules/maker/hooks/useResultTerms";

interface ProductionTableProps {
  orders: ProductionOrder[];
  /** Ordering the list is in — reflected as `aria-sort` on the date column. */
  sort: string;
  /** Absent for an account that may not write — the action is then not offered. */
  onDuplicate?: (orderId: string, event: React.MouseEvent) => void;
  isDuplicating: boolean;
}

/**
 * Production runs as rows.
 *
 * Same records and same actions as the cards; the table exists because a run
 * is mostly numbers — quantity, cost, result — and columns compare them where
 * a grid of cards cannot.
 */
export function ProductionTable({
  orders,
  sort,
  onDuplicate,
  isDuplicating,
}: ProductionTableProps) {
  const { t, i18n } = useTranslation("maker");
  const resultTerm = useResultTerms();
  const resultDefinitionId = useId();
  const navigate = useNavigate();
  const currency = useOrganizationCurrency();

  // One line per heading — a wrapped "Result" doubles the header band.
  const headerClass =
    "px-3 py-2.5 font-medium text-on-secondary uppercase text-xs tracking-wide whitespace-nowrap";

  return (
    <Card className="overflow-hidden">
      <div className="relative overflow-x-auto">
        <table className="w-full text-sm min-w-[720px]">
          <thead>
            <tr className="border-b border-border text-left">
              <th scope="col" className={headerClass}>
                {t("productionList.table.product")}
              </th>
              <th scope="col" className={headerClass}>
                {t("productionList.table.status")}
              </th>
              <th scope="col" className={`${headerClass} text-right`}>
                {t("productionList.card.qty")}
              </th>
              <th scope="col" className={`${headerClass} text-right`}>
                {t("productionList.card.cost")}
              </th>
              <th
                scope="col"
                className={`${headerClass} text-right`}
                aria-describedby={resultDefinitionId}
              >
                {resultTerm.label}
              </th>
              <th
                scope="col"
                className={headerClass}
                aria-sort={
                  sort === "newest"
                    ? "descending"
                    : sort === "oldest"
                      ? "ascending"
                      : undefined
                }
              >
                {t("productionList.table.date")}
              </th>
              <th scope="col" className="px-3 py-2.5">
                <span className="sr-only">
                  {t("productionList.table.actions")}
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            {orders.map((order) => {
              const result =
                order.status === "COMPLETED" &&
                order.result_per_unit !== null &&
                order.actual_qty !== null
                  ? Number(order.result_per_unit) * Number(order.actual_qty)
                  : null;
              return (
                <tr
                  key={order.id}
                  className="border-b border-border last:border-0 hover:bg-surface-muted"
                >
                  <td className="px-3 py-2.5 font-medium text-on">
                    <span className="block truncate max-w-[260px]">
                      {/* The name is the row's one way in — a real link, so
                          Enter, the middle button and "open in a new tab"
                          all reach the order. The row-wide click it used to
                          carry ate all three. */}
                      <Link
                        to={`/maker/production/${order.id}`}
                        className="rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background hover:text-accent"
                      >
                        {order.output_template_name ?? (
                          <span className="font-mono text-xs text-on-muted">
                            {order.id.slice(0, 8)}…
                          </span>
                        )}
                      </Link>
                    </span>
                  </td>
                  <td className="px-3 py-2.5">
                    <ProductionStatusBadge status={order.status} />
                    {/* The grid card names the blocker; the row the planner
                        scans in a hurry may not say less. */}
                    <ProductionShortageSignal count={order.shortage_count} />
                  </td>
                  <td className="px-3 py-2.5 text-right whitespace-nowrap">
                    {formatQuantityLocalized(
                      t,
                      order.planned_qty,
                      order.output_uom_symbol,
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-right text-on-secondary whitespace-nowrap tabular-nums">
                    {order.total_cost === null
                      ? "—"
                      : formatMoney(order.total_cost, currency, i18n.language)}
                  </td>
                  <td
                    className={`px-3 py-2.5 text-right font-medium whitespace-nowrap ${
                      result === null
                        ? "text-on-muted"
                        : result >= 0
                          ? "text-accent-600"
                          : "text-red-500"
                    }`}
                  >
                    {result === null
                      ? "—"
                      : formatMoney(result, currency, i18n.language)}
                  </td>
                  <td className="px-3 py-2.5 text-on-muted whitespace-nowrap">
                    {formatDate(order.created_at)}
                  </td>
                  <td className="px-3 py-2.5 text-right whitespace-nowrap">
                    {/* Pre-0a orders carry no recipe reference — the same
                        rule the card follows: no offer that leads nowhere. */}
                    {order.recipe_id && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() =>
                          navigate(`/maker/recipes/${order.recipe_id}`)
                        }
                        data-testid="maker-row-view-recipe-button"
                      >
                        {t("productionList.viewRecipe")}
                      </Button>
                    )}
                    {onDuplicate && (
                      <DuplicateOrderButton
                        orderId={order.id}
                        isDuplicating={isDuplicating}
                        onDuplicate={onDuplicate}
                        testId="maker-row-duplicate-button"
                      />
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {/* Said under the table, not in a hover title: a title never reaches
          a keyboard or a finger. */}
      <p
        id={resultDefinitionId}
        className="border-t border-border px-3 py-2 text-xs text-on-muted"
      >
        {resultTerm.label}: {resultTerm.definition}
      </p>
    </Card>
  );
}
