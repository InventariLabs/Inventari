import type { TFunction } from "i18next";
import { unitLabel } from "@/lib/i18nHelpers";
import type { WmsPickScanResult } from "@/modules/warehouse/api/documents_picking";

/**
 * The sentence for a scan the dispatch does not take: a product that is not
 * on it, or one whose line is already picked or skipped. It names the product
 * the picker read.
 */
export function pickRefusal(
  t: TFunction,
  result: WmsPickScanResult | null | undefined,
): string | null {
  if (result?.status === "not_in_document") {
    return t("warehouse:picking.toast.not_in_document", {
      product: result.product_name ?? "",
    });
  }
  if (result?.status === "already_picked") {
    return t("warehouse:picking.toast.already_picked", {
      product: result.product_name ?? "",
      qty: result.picked_quantity,
      expected: result.expected_quantity,
      uom: unitLabel(t, result.uom_symbol),
    });
  }
  if (result?.status === "line_skipped") {
    // Nothing was picked of it: the line was put off, and its card offers
    // the Undo skip that brings it back.
    return t("warehouse:picking.toast.line_skipped", {
      product: result.product_name ?? "",
    });
  }
  return null;
}
