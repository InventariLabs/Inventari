import { lineAmounts } from "@/utils/money";

/**
 * Pure subtotal calculation for a purchase-order line.
 *
 * Lives in a dedicated module (rather than inside `PurchaseOrderFormModal.tsx`)
 * to break the former import cycle between the form modal and the line editor.
 *
 * `PurchaseOrderFormModal` re-exports this helper for backward compatibility,
 * but the canonical source is here. Import directly from this module in new code.
 *
 * @param qty     Quantity ordered.
 * @param price   Unit price as a string (from a number input).
 * @param taxRate VAT/tax rate as a string percentage (e.g. "23" for 23%).
 * @returns The gross line subtotal formatted to 2 decimals, or "" if invalid.
 */

export function computeLineValueWithTax(
  qty: number,
  price: string,
  taxRate: string,
): string {
  const p = parseFloat(price);
  if (!isFinite(p) || p < 0) return "";
  // The backend's rule, so the preview and the saved line agree: net and tax
  // are each rounded, and the gross is their sum. Multiplying by (1 + rate)
  // and rounding once gave a different answer whenever the line's own tax
  // landed on a half.
  return lineAmounts(qty, p, taxRate).gross.toFixed(2);
}
