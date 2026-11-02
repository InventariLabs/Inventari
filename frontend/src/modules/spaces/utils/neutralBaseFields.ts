import type { LucideIcon } from "lucide-react";
import {
  Barcode,
  Banknote,
  FileText,
  Hash,
  MapPin,
  Package,
  Tag,
  Type,
} from "lucide-react";

/**
 * Neutral base fields shown on storage configuration screens.
 *
 * The storage defines only universal "base" fields common to everything stored
 * there. Vertical-specific fields (freeze_date, expiry_date, serial_number,
 * deposit, warranty, …) live on the **category** via Category.field_definitions
 * and are merged at item-form render time. Mixed-use storages therefore work
 * out of the box: jam shows expiry_date from its category, bleach doesn't.
 */

export const NEUTRAL_BASE_FIELDS_ALWAYS_ON = [
  "name",
  "quantity",
  "unit",
] as const;

export const NEUTRAL_BASE_FIELDS_TOGGLEABLE = [
  "barcode",
  "sku",
  "price",
  "notes",
  "shelf_location",
] as const;

export type NeutralBaseFieldKey =
  | (typeof NEUTRAL_BASE_FIELDS_ALWAYS_ON)[number]
  | (typeof NEUTRAL_BASE_FIELDS_TOGGLEABLE)[number];

export const NEUTRAL_BASE_FIELD_ICONS: Record<NeutralBaseFieldKey, LucideIcon> =
  {
    name: Type,
    quantity: Hash,
    unit: Package,
    barcode: Barcode,
    sku: Tag,
    price: Banknote,
    notes: FileText,
    shelf_location: MapPin,
  };

/**
 * i18n label keys under `locations:fieldLabels.*`. Kept identical to the field
 * key itself (matches existing convention for non-prefixed keys).
 */
export const NEUTRAL_BASE_FIELD_LABEL_KEYS: Record<
  NeutralBaseFieldKey,
  string
> = {
  name: "name",
  quantity: "quantity",
  unit: "unit",
  barcode: "barcode",
  sku: "sku",
  price: "price",
  notes: "notes",
  shelf_location: "shelf_location",
};

/**
 * Returns the toggleable neutral base fields.
 *
 * Kept as a function (not a constant) for stable call sites; the
 * contextTag argument is intentionally ignored: storage is now vertical-
 * agnostic. Pass `undefined` to make the no-op intent explicit.
 */
export function getNeutralBaseFields(
  _contextTag?: string | null,
): readonly NeutralBaseFieldKey[] {
  return NEUTRAL_BASE_FIELDS_TOGGLEABLE;
}
