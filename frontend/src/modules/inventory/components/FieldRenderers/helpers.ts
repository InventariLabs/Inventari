import { FieldDefinition } from "@/types";
import { logger } from "@/utils/logger";

/**
 * Helpers for UnifiedFieldRenderer
 */

/**
 * True when i18next actually found a translation for `key`.
 *
 * On a miss i18next echoes the key back with any `ns:` prefix **stripped**, so
 * comparing the result against the key we passed in ("items:itemBrand") never
 * matches the value we get back ("itemBrand") — the guard silently passes and
 * the raw key leaks into the form. Compare against both shapes.
 */
function isResolved(key: string, translated: string): boolean {
  const bare = key.includes(":") ? key.split(/:(.+)/)[1] : key;
  return translated !== key && translated !== bare;
}

/**
 * True when a string is an i18n key or code identifier rather than a label a
 * human typed. Custom fields carry free-text labels ("Warranty until") that
 * must survive verbatim; dotted keys ("fields.purchase_price") and camelCase
 * identifiers ("itemBrand") must not reach the UI.
 */
function looksLikeKey(value: string): boolean {
  if (!/^[A-Za-z][\w.:-]*$/.test(value)) return false;
  return value.includes(".") || value.includes(":") || /[a-z][A-Z]/.test(value);
}

export function getPlaceholder(
  field: FieldDefinition,
  unit?: string,
  tDyn?: (key: string, opts?: Record<string, unknown>) => string,
): string {
  if (!tDyn) return field.placeholder || "";

  if (field.placeholder) {
    const translated = String(tDyn(field.placeholder));
    if (isResolved(field.placeholder, translated)) return translated;
    // An unresolved key is a config bug — an empty placeholder is a better
    // hint than "placeholders.description" rendered inside the input.
    return looksLikeKey(field.placeholder) ? "" : field.placeholder;
  }

  // Check for nested placeholders in items namespace
  const nestedKey = `items:placeholders.${field.key}`;
  const translated = String(tDyn(nestedKey));
  if (isResolved(nestedKey, translated)) return translated;

  if (field.key === "quantity") {
    const u = unit || "pcs";
    const decimalKeys = ["kg", "l"];
    const smallKeys = ["g", "ml"];
    const example = decimalKeys.includes(u)
      ? "items:placeholders.quantityDecimal"
      : smallKeys.includes(u)
        ? "items:placeholders.quantitySmall"
        : "items:placeholders.quantity";
    return String(tDyn(example, { defaultValue: "" }));
  }

  return "";
}

export function getLabel(
  field: FieldDefinition,
  tDyn?: (key: string, opts?: Record<string, unknown>) => string,
): string {
  // The wire types a label as optional-nullable; a definition without one
  // falls through to the same untitled-field handling below.
  const label = field.label ?? "";
  if (!tDyn) return label || "";

  // A system field's label is the platform's copy, catalogued under the
  // field's key (items:fields.<key>) — the reader's language picks the
  // entry, whatever language the seeding ran in. A user field never takes
  // this path: its label is the user's own words, not copy to translate.
  if (field.is_system) {
    const byKey = `items:fields.${field.key}`;
    const translated = String(tDyn(byKey));
    if (isResolved(byKey, translated)) return translated;
  }

  // If it's a key with namespace, translate it
  if (label.includes(":")) {
    const translated = String(tDyn(label));
    if (isResolved(label, translated)) return translated;
  } else {
    // Try in items namespace first
    const itemsKey = `items:${label}`;
    const translated = String(tDyn(itemsKey));
    if (isResolved(itemsKey, translated)) return translated;

    // Fallback to common namespace
    const commonResult = String(tDyn(label, { ns: "common" }));
    if (isResolved(label, commonResult)) return commonResult;
  }

  // Last-resort fallback for labels that are i18n keys or code identifiers
  // ("fields.purchase_price", "itemBrand") rather than human-readable strings.
  // The fallback is intentional but a config bug in disguise — surface it
  // loudly so it shows up in dev consoles instead of silently masking the
  // missing i18n key (or unsaved custom-field label). A plain capitalized word
  // ("Brand", "Quantity") is a valid human label — the shape check keeps the
  // heuristic from misfiring on it.
  if (looksLikeKey(label)) {
    logger.warn(
      "[getLabel] No i18n key for field label that looks like a code identifier:",
      label,
      "(field.key:",
      field.key,
      "). Falling back to items:untitledField. Add the missing key or fix the field's label.",
    );
    return String(
      tDyn("items:untitledField", { defaultValue: "Untitled field" }),
    );
  }

  return label;
}
