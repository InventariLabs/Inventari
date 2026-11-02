import type { Uom } from "@/types";
import type { PreviewIngredient } from "@/modules/recipes/types/nutrition";
import { isSpiceQuantity } from "../utils";

export function willBeSpice(
  quantity: string,
  uomId: string | null,
  allUoms: Uom[],
): boolean {
  if (!uomId) return false;
  const qty = parseFloat(quantity);
  if (isNaN(qty)) return false;
  const sym = allUoms.find((u) => u.id === uomId)?.symbol ?? null;
  return isSpiceQuantity(qty, sym);
}

export interface IngredientDraft {
  _key: number;
  name: string;
  quantity: string;
  uom_id: string | null;
  original_text: string | null;
  group_name: string | null;
  template_id: string | null;
  template_name: string | null;
  is_optional: boolean;
  is_spice_forced: boolean;
  allergens: string[];
  original_unit_text: string | null;
  /** The unit text the import could not match to a unit; null when it matched or named none. */
  unread_unit: string | null;
  unit_display: string | null;
  metric_quantity: string;
  conversion_ratio: number;
}

/** What the review's edit callbacks carry for one draft field. */
export type DraftValue = string | boolean | string[] | null;

export function previewToDraft(
  ing: Pick<PreviewIngredient, "name" | "quantity"> &
    Partial<PreviewIngredient>,
  key: number,
): IngredientDraft {
  const hasOriginal =
    ing.original_quantity != null && ing.original_unit_text != null;
  const displayQty = hasOriginal ? ing.original_quantity! : ing.quantity;
  const metricQty = ing.quantity;
  const ratio = hasOriginal && displayQty !== 0 ? metricQty / displayQty : 1;
  return {
    _key: key,
    name: ing.name,
    quantity: String(parseFloat(displayQty.toFixed(3))),
    uom_id: ing.uom_id ?? null,
    original_text: ing.original_text ?? null,
    group_name: ing.group_name ?? null,
    template_id: ing.template_id ?? null,
    template_name: ing.template_name ?? null,
    is_optional: ing.is_optional ?? false,
    is_spice_forced: ing.is_spice ?? false,
    allergens: ing.allergens ?? [],
    original_unit_text: hasOriginal ? (ing.original_unit_text ?? null) : null,
    unread_unit: ing.uom_id ? null : (ing.original_unit_text ?? null),
    unit_display: hasOriginal ? (ing.unit_display ?? null) : null,
    metric_quantity: String(parseFloat(metricQty.toFixed(3))),
    conversion_ratio: ratio,
  };
}

/** A named line with no unit: its amount could not be weighed or shopped for. */
export function lacksUnit(ing: Pick<IngredientDraft, "name" | "uom_id">) {
  return ing.name.trim() !== "" && !ing.uom_id;
}

export function composeDisplayText(ing: IngredientDraft): string | null {
  const name = ing.name.trim();
  if (!name || !ing.original_unit_text) return null;
  const unit = (ing.unit_display ?? ing.original_unit_text).trim();
  const qty = ing.quantity.trim() || "1";
  return unit ? `${name} - ${qty} ${unit}` : `${name} - ${qty}`;
}
