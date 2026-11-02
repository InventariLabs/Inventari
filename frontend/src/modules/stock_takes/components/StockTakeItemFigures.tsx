import { useTranslation } from "react-i18next";
import { ChevronRight } from "lucide-react";
import type { StockTakeItem } from "@/modules/stock_takes/types/stock-takes";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";

interface Props {
  stockTakeItem: StockTakeItem;
  savedCount: number | null;
  discrepancy: "missing" | "surplus" | null;
}

/**
 * What the records hold, what was counted, and the gap — in the row's unit.
 *
 * Bananas are weighed and yoghurt is counted, and the card said neither: two
 * rows reading "Expected: 2.300" look identical, and whoever sees twelve in
 * the basket types twelve kilograms. Every other screen in this chain carries
 * the symbol — the moves register, the stock list, the product card — and this
 * is the one where somebody types the number.
 *
 * All three figures go through `formatQuantityLocalized`, the one place that
 * decides how a quantity reads: the number the reader's language writes, in
 * the places the unit's own step leaves (`uom_rounding` — a kilogram divides
 * and a piece does not), next to the word the reader's language has for the
 * unit. Printing the catalogue's own symbol put "0 pcs" on this card where
 * the product list beside it said "0 szt.", about the same screws.
 */
export default function StockTakeItemFigures({
  stockTakeItem,
  savedCount,
  discrepancy,
}: Props) {
  const { t } = useTranslation(["stock_takes", "common"]);
  const unit = stockTakeItem.uom_symbol?.trim() || null;
  const withUnit = (value: number | string | null | undefined) =>
    formatQuantityLocalized(t, value, unit, stockTakeItem.uom_rounding);
  // A unit found away from its location: on this one nothing of it was
  // expected, as the report states it.
  const expectedHere = stockTakeItem.expected_location_id
    ? 0
    : stockTakeItem.system_quantity;
  const difference =
    savedCount === null ? null : savedCount - Number(expectedHere);

  return (
    <div className="flex items-center gap-4 mt-2 text-sm tabular-nums">
      <span className="text-on-secondary">
        {t("item.expected")}: <strong>{withUnit(expectedHere)}</strong>
      </span>
      <ChevronRight size={16} className="text-on-muted" />
      <span
        className={
          discrepancy
            ? "text-on-warning font-medium"
            : "text-on-success font-medium"
        }
      >
        {t("item.counted")}:{" "}
        <strong>{savedCount === null ? "—" : withUnit(savedCount)}</strong>
      </span>
      {discrepancy && difference !== null && (
        // Rounded to the scale the quantity columns keep: subtracting in
        // binary floating point printed a difference of −0.3 as
        // "(-0.2999999999999998)" on the card somebody copies onto a slip
        // of paper.
        <span className="text-on-warning">
          ({difference > 0 ? "+" : ""}
          {withUnit(difference)})
        </span>
      )}
    </div>
  );
}
