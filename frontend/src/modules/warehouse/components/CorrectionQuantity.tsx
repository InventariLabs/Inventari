import { useTranslation } from "react-i18next";
import { correctionStockSign } from "@/modules/warehouse/types";
import type { WarehouseDocument } from "@/modules/warehouse/types";

/**
 * What a correction line does to the stock.
 *
 * A line is a signed difference on the document it corrects, and which way
 * that moves stock depends on that document: less issued puts goods back.
 * The summary above the lines counts stock, so the line says the same — the
 * number as it lands on the shelf and a sentence for the direction — instead
 * of the bare difference, which read "-1" under a summary of "+1".
 */
function onStock(document: WarehouseDocument, difference: number): number {
  return correctionStockSign(document.corrects_document_type) * difference;
}

/** The line's number, signed as the stock moves. */
export function CorrectionQuantity({
  document,
  difference,
  formatQuantity,
}: {
  document: WarehouseDocument;
  /** The line's difference, as the correction states it. */
  difference: number;
  formatQuantity: (value: number) => string;
}) {
  const quantity = onStock(document, difference);
  return (
    <span className={quantity >= 0 ? "text-accent-600" : "text-red-600"}>
      {quantity >= 0 ? "+" : ""}
      {formatQuantity(quantity)}
    </span>
  );
}

/** The same direction in plain words. */
export function CorrectionDirection({
  document,
  difference,
}: {
  document: WarehouseDocument;
  difference: number;
}) {
  const { t } = useTranslation("warehouse");
  const quantity = onStock(document, difference);
  if (quantity === 0) return null;
  return (
    <span className="font-sans text-xs text-on-secondary">
      {quantity > 0
        ? t("detail.correctionAddsToStock")
        : t("detail.correctionTakesFromStock")}
    </span>
  );
}
