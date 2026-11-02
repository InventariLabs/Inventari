import type { Item } from "@/types";
import { formatDate } from "@/utils/helpers";
import type { TFunction } from "i18next";

// Category names travel as English literals persisted
// with the declaration. Static keys keep the i18n unused-key gate honest
// (a dynamic template literal would flag all eight as orphans).
const CATEGORY_CODE_KEYS: Record<string, string> = {
  LAPTOP: "categories.codes.LAPTOP",
  DESKTOP: "categories.codes.DESKTOP",
  MONITOR: "categories.codes.MONITOR",
  PHONE: "categories.codes.PHONE",
  NETWORK_DEVICE: "categories.codes.NETWORK_DEVICE",
  PERIPHERAL: "categories.codes.PERIPHERAL",
  SERVER: "categories.codes.SERVER",
  OTHER_EQUIPMENT: "categories.codes.OTHER_EQUIPMENT",
};

/**
 * The translator these label helpers need: a key and a fallback.
 *
 * Structural rather than i18next's `TFunction` so components that receive
 * `t` as a plain prop — the dynamic-fields card does — can pass it through
 * instead of rendering the raw English name beside translated siblings.
 */
export type LabelTranslate =
  TFunction | ((key: string, fallback?: string) => string);

/** Both shapes accept (key, fallback); the union just cannot say so. */
function translate(t: LabelTranslate, key: string, fallback: string): string {
  return (t as (key: string, fallback?: string) => string)(key, fallback);
}

export function getCategoryLabel(
  t: LabelTranslate,
  category: { code?: string | null; name: string },
): string {
  const key = category.code ? CATEGORY_CODE_KEYS[category.code] : undefined;
  return key ? translate(t, key, category.name) : category.name;
}

export function getEquipmentMeta(item: Item) {
  const meta = item.metadata?.equipment as Record<string, unknown> | undefined;
  return {
    // The serial number lives in the core column — the one place every write
    // path fills and the only one core search can reach. The namespace is
    // read after it, for rows written before that was true.
    serial_number:
      item.serial_number ?? (meta?.serial_number as string) ?? null,
    asset_tag: (meta?.asset_tag as string) ?? null,
    // An asset created outside the equipment paths (a plain POST /items
    // under an equipment category) carries no equipment namespace at all —
    // the create interceptor seeds a status only where one already exists.
    // Null travels: the badge says unknown, nothing claims a state nobody
    // recorded.
    status: (meta?.equipment_status as string) ?? null,
    manufacturer: (meta?.manufacturer as string) ?? item.brand ?? null,
    model: (meta?.model as string) ?? null,
    /** The model this unit was created from, when it was created from one. */
    model_id: (meta?.model_id as string) ?? null,
    purchase_date: (meta?.purchase_date as string) ?? null,
    warranty_until: (meta?.warranty_until as string) ?? null,
    notes: (meta?.notes as string) ?? null,
  };
}

/**
 * Whether handing the asset to someone may be offered. An action gate, not
 * a claim: an asset whose status nobody set is never *called* available,
 * but with nobody holding it the checkout stays on offer — the assignment
 * service, not the badge, refuses what cannot happen.
 */
export function checkoutOfferable(status: string | null): boolean {
  return status === null || status === "AVAILABLE";
}

/**
 * How many assets the fleet holds: the register without the retired ones, as
 * the composition bars count it. The overview's sentence and its first tile
 * both read this, so the two cannot name different totals.
 */
export function fleetSize(counts: {
  total_assets: number;
  retired: number;
}): number {
  return counts.total_assets - counts.retired;
}

/**
 * What tells two units of one model apart, or null when nothing does.
 *
 * The asset table has read these in this order in one column for as long as
 * it has existed. The dashboard's assignment rows named the model alone, so
 * four "PowerEdge R650" in a row left the reader sent to fetch one of them
 * no way of knowing which.
 */
export function unitIdentifier(unit: {
  item_serial?: string | null;
  item_asset_tag?: string | null;
  item_barcode?: string | null;
}): string | null {
  return unit.item_serial ?? unit.item_asset_tag ?? unit.item_barcode ?? null;
}

export const fmt = formatDate;

/**
 * model select label without the duplicated brand — "Dell Dell
 * Latitude 5540 (standard)" happens when the model name already starts
 * with the brand.
 */
export function formatModelDisplayName(model: {
  brand?: string | null;
  name: string;
}): string {
  const name = model.name.trim();
  const brand = (model.brand ?? "").trim();
  if (brand && name && !name.toLowerCase().startsWith(brand.toLowerCase())) {
    return `${brand} ${name}`;
  }
  return name || brand;
}

/**
 * Catalogue order is the order its cards read: by the display label —
 * the brand prepended where the name does not carry it — compared under
 * the UI language's rules, not the backend's byte order over the raw
 * name. Byte order filed "MacBook Pro 14 M3" under M while the card read
 * "Apple MacBook Pro 14 M3", and put every uppercase U before a
 * lowercase i.
 */
export function sortModelsForDisplay<
  T extends { brand?: string | null; name: string },
>(models: readonly T[], lang: string): T[] {
  const collator = new Intl.Collator(lang, {
    sensitivity: "base",
    numeric: true,
  });
  return [...models].sort((a, b) =>
    collator.compare(formatModelDisplayName(a), formatModelDisplayName(b)),
  );
}
