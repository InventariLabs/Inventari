import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/Badge";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { formatDate } from "@/utils/formatters";
import type { NeedRow, NeedsView } from "@/modules/maker/types/maker";

/**
 * One list of what the planned runs of a period need: per ingredient what is
 * needed, what is in stock, what open purchase orders still expect (and when)
 * and what is still missing.
 *
 * With purchasing off the on-order column is not there at all — nothing on
 * order is not the same as not knowing about orders. An ingredient with a
 * recipe of its own is marked "make": its missing part is a run to plan, not a
 * purchase.
 */
export function NeedsTable({ view }: { view: NeedsView }) {
  const { t } = useTranslation("maker");
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm" data-testid="maker-needs-table">
        <thead>
          <tr className="border-b border-border text-left text-xs text-on-secondary">
            <th scope="col" className="px-3 py-2 font-medium">
              {t("planning.needs.ingredient")}
            </th>
            <th scope="col" className="px-3 py-2 font-medium text-right">
              {t("planning.needs.needed")}
            </th>
            <th scope="col" className="px-3 py-2 font-medium text-right">
              {t("planning.needs.inStock")}
            </th>
            {view.purchasing && (
              <th scope="col" className="px-3 py-2 font-medium text-right">
                {t("planning.needs.onOrder")}
              </th>
            )}
            <th scope="col" className="px-3 py-2 font-medium text-right">
              {t("planning.needs.missing")}
            </th>
          </tr>
        </thead>
        <tbody>
          {view.rows.map((row) => (
            <NeedsRow
              key={row.template_id}
              row={row}
              purchasing={view.purchasing}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function NeedsRow({ row, purchasing }: { row: NeedRow; purchasing: boolean }) {
  const { t } = useTranslation("maker");
  const qty = (value: string | number) =>
    formatQuantityLocalized(t, value, row.uom_symbol);
  const short = Number(row.missing) > 0;
  return (
    <tr className="border-b border-border last:border-0 align-top">
      <td className="px-3 py-2 font-medium text-on">
        {row.name}
        {row.action === "make" && (
          <Badge variant="info" className="ml-2">
            {t("planning.needs.make")}
          </Badge>
        )}
        {Number(row.planned) > 0 && (
          <div className="text-xs font-normal text-on-secondary">
            {t("planning.needs.planned", { qty: qty(row.planned) })}
          </div>
        )}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">{qty(row.needed)}</td>
      <td className="px-3 py-2 text-right tabular-nums">{qty(row.in_stock)}</td>
      {purchasing && (
        <td className="px-3 py-2 text-right tabular-nums">
          {qty(row.on_order ?? 0)}
          {row.expected.map((delivery) => (
            <div
              key={`${delivery.purchase_order_id}-${delivery.expected_date}`}
              className="text-xs text-on-secondary"
            >
              {delivery.number}
              {" · "}
              {qty(delivery.quantity)}
              {" · "}
              {delivery.expected_date
                ? formatDate(delivery.expected_date)
                : t("planning.needs.noDate")}
            </div>
          ))}
        </td>
      )}
      <td
        className={`px-3 py-2 text-right tabular-nums ${
          short ? "font-medium text-on-danger" : "text-on-secondary"
        }`}
      >
        {qty(row.missing)}
      </td>
    </tr>
  );
}
