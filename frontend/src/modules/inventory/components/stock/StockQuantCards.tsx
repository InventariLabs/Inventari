/**
 * The shelves on a phone — one card a shelf.
 *
 * Six columns wrap into gibberish on a narrow screen, so the card leads
 * with the place and the number a picker can actually take.
 */
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/Badge";
import { formatDecimalQty } from "@/utils/formatters";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import type { StockQuantRow } from "@/lib/api/stockQuants";
import { useStorageLocationLabels } from "@/modules/shared/hooks/useStorageLocationLabels";

interface StockQuantCardsProps {
  rows: StockQuantRow[];
}

export function StockQuantCards({ rows }: StockQuantCardsProps) {
  const { t } = useTranslation(["inventory", "common"]);
  const placeName = useStorageLocationLabels(
    rows.map((row) => row.location_id),
  );

  const quantity = (
    value: string | number,
    symbol: string | null | undefined,
  ) => formatQuantityLocalized(t, formatDecimalQty(value), symbol);

  return (
    <ul className="space-y-3">
      {rows.map((row) => (
        <li
          key={row.id}
          className="bg-surface-card rounded-xl shadow-sm border border-border p-4 space-y-2"
        >
          <div className="flex items-start justify-between gap-3">
            <span className="font-medium text-on">
              {row.product_name ?? "—"}
            </span>
            <span className="tabular-nums text-on whitespace-nowrap">
              {quantity(row.available_quantity, row.uom_symbol)}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-on-muted">
            <span>
              {[
                placeName(row.location_id, row.location_name),
                row.lot_name,
                Number(row.reserved_quantity) > 0
                  ? t("inventory:stock.reservedShort", {
                      quantity: quantity(row.reserved_quantity, row.uom_symbol),
                    })
                  : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </span>
            {row.lot_status && row.lot_status !== "active" ? (
              <Badge variant="warning">
                {t(`inventory:lot.status.${row.lot_status}`, {
                  defaultValue: row.lot_status,
                })}
              </Badge>
            ) : null}
          </div>
        </li>
      ))}
    </ul>
  );
}
