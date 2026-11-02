import { Uom } from "@/types";
import type { ItemFormData } from "./useItemForm";
import type { UomCategory } from "@/types";
import { findUom } from "@/modules/shared/hooks/useUoms";

/** Restates a quantity in a new unit.
 *
 * Within one category the value converts through the units' factors — 500 g
 * is 0.5 kg, and leaving it at 500 would turn half a kilo into half a tonne.
 * Across categories there is no conversion (grams are not pieces), so the
 * quantity is cleared rather than silently reinterpreted.
 */
export function convertQuantity(
  quantity: string,
  from: Uom | null,
  to: Uom | null,
): string {
  if (!quantity) return quantity;
  if (!from || !to || from.id === to.id) return quantity;
  if (from.category_id !== to.category_id) return "";

  const value = parseFloat(quantity);
  // The wire carries a factor as a decimal string.
  const fromFactor = Number(from.factor);
  const toFactor = Number(to.factor);
  if (isNaN(value) || !toFactor) return quantity;

  const converted = (value * fromFactor) / toFactor;
  // Trim the float noise that 500 / 1000 * 1000 leaves behind.
  return String(Number(converted.toFixed(6)));
}

/** The form edits the product's unit weight, which lives on its template —
 * the item itself carries only a computed total (ADR-015). */
export function templateWeight(
  initialData: Partial<ItemFormData> | undefined,
): {
  weight?: string;
  weight_uom_id?: string;
} {
  const template = initialData?.template as
    { weight_value?: number | null; weight_uom_id?: string | null } | undefined;
  if (!template?.weight_value) return {};
  return {
    weight: String(template.weight_value),
    weight_uom_id: template.weight_uom_id ?? undefined,
  };
}

/**
 * Quantity re-expressed in the unit the reader switched to. `undefined` when
 * the two units measure different things — grams do not convert to pieces.
 */
export function convertedQuantity(
  formData: ItemFormData,
  nextUomId: string,
  uomCategories: UomCategory[] | undefined,
): string {
  return convertQuantity(
    formData.quantity,
    findUom(uomCategories, formData.uom_id),
    findUom(uomCategories, nextUomId),
  );
}
