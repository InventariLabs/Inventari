/**
 * The shelves as a table — the desktop reading.
 *
 * A list of records is a `<table>` (UI_GUIDELINES §14.1). Rows arrive
 * ordered by place, which is how a picker walks the building, so the place
 * column is the one carrying `aria-sort`.
 */
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/Badge";
import { formatDecimalQty } from "@/utils/formatters";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import type { StockQuantRow } from "@/lib/api/stockQuants";
import { useStorageLocationLabels } from "@/modules/shared/hooks/useStorageLocationLabels";

interface StockQuantsTableProps {
  rows: StockQuantRow[];
  linkToBatches?: boolean;
}

/** Held, quarantined and recalled all mean "do not pick it" — say which. */
const STATUS_TONE: Record<string, "warning" | "danger"> = {
  quarantined: "warning",
  held: "warning",
  expired: "danger",
  recalled: "danger",
};

export function StockQuantsTable({
  rows,
  linkToBatches = true,
}: StockQuantsTableProps) {
  const { t } = useTranslation(["inventory", "common"]);
  const placeName = useStorageLocationLabels(
    rows.map((row) => row.location_id),
  );

  const quantity = (
    value: string | number,
    symbol: string | null | undefined,
  ) => formatQuantityLocalized(t, formatDecimalQty(value), symbol);

  return (
    <div className="bg-surface-card rounded-xl sm:rounded-2xl shadow-sm border border-border overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-surface-raised border-b border-border text-xs font-medium text-on-secondary uppercase tracking-wider">
              <th scope="col" className="px-4 py-3" aria-sort="ascending">
                {t("inventory:stock.columns.location")}
              </th>
              <th scope="col" className="px-4 py-3">
                {t("inventory:stock.columns.product")}
              </th>
              <th scope="col" className="px-4 py-3">
                {t("inventory:stock.columns.batch")}
              </th>
              <th scope="col" className="px-4 py-3 text-right">
                {t("inventory:stock.columns.quantity")}
              </th>
              <th scope="col" className="px-4 py-3 text-right">
                {t("inventory:stock.columns.reserved")}
              </th>
              <th scope="col" className="px-4 py-3 text-right">
                {t("inventory:stock.columns.available")}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.id}
                className="border-b border-border last:border-0 text-sm hover:bg-surface-raised/50"
              >
                <td className="px-4 py-2.5 text-on">
                  {placeName(row.location_id, row.location_name) ?? "—"}
                </td>
                <td className="px-4 py-2.5 text-on">
                  {row.product_name ?? "—"}
                </td>
                <td className="px-4 py-2.5 text-on-secondary">
                  {row.lot_id && row.lot_name ? (
                    <span className="inline-flex items-center gap-2">
                      {linkToBatches ? (
                        <Link
                          to={`/inventory/lots/${row.lot_id}`}
                          className="text-on-primary hover:underline"
                        >
                          {row.lot_name}
                        </Link>
                      ) : (
                        <span>{row.lot_name}</span>
                      )}
                      {/* A recalled batch is invisible on the shelf
                          otherwise, and the refusal only arrives at picking
                          time. */}
                      {row.lot_status && STATUS_TONE[row.lot_status] && (
                        <Badge variant={STATUS_TONE[row.lot_status]}>
                          {t(`inventory:lot.status.${row.lot_status}`, {
                            defaultValue: row.lot_status,
                          })}
                        </Badge>
                      )}
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-on whitespace-nowrap">
                  {quantity(row.quantity, row.uom_symbol)}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-on-secondary whitespace-nowrap">
                  {Number(row.reserved_quantity) === 0
                    ? "—"
                    : quantity(row.reserved_quantity, row.uom_symbol)}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums font-medium text-on whitespace-nowrap">
                  {quantity(row.available_quantity, row.uom_symbol)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
