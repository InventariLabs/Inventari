import type { TFunction } from "i18next";

import { formatQuantityValue } from "@/utils/formatters";
import type { TranslateFn } from "@/types/i18n";

/**
 * Wraps the i18next `t` function to accept fully-dynamic string keys without
 * TypeScript complaining about key union exhaustiveness.
 *
 * Usage:
 *   const tDynamic = makeTDynamic(t);
 *   tDynamic(`statuses.${status}`)
 */
export function makeTDynamic(
  t: TFunction,
): (key: string, opts?: Record<string, unknown>) => string {
  return (key: string, opts?: Record<string, unknown>) =>
    t(key as Parameters<typeof t>[0], opts) as string;
}

/**
 * A unit of measure as the reader's language writes it.
 *
 * The one place the word comes from. The symbol on the record is the
 * catalogue's own ("pcs"), and printing it verbatim put "6 pcs" in a sheet
 * whose list underneath said "6 SZT."; a picking dialog said "3 szt." on one
 * line and "3 pcs" on the next, about the same position. The translation
 * lives under `common:units.<symbol>` — mirrored in the backend and guarded
 * by `check-units-labels`, which is why it and not one of the two catalogues
 * that used to stand beside it; a unit nobody translated keeps its symbol,
 * which is a better answer than an empty string.
 *
 * Callers with an amount in hand want `formatQuantityLocalized`, which is
 * this with the number in front. The `unit-symbol-unresolved` detector keeps
 * the raw symbol out of every other render.
 *
 * The WMS screens route their quantity sentences here as well, and the
 * record with no unit gives them nothing: the answer used to be an em dash,
 * and a dash printed straight after a quantity — "1 —", "expected 1 —" —
 * reads as a unit called "—". Nothing stands where the unit would. A
 * table's own "no value" column is a different question and keeps its dash;
 * the capacity rows on a location carry theirs with a tooltip.
 */
export function unitLabel(
  t: TranslateFn,
  symbol: string | null | undefined,
): string {
  const unit = symbol?.trim();
  if (!unit) return "";
  return t(`common:units.${unit}`, { defaultValue: unit });
}

/**
 * A product category as the reader's language names it.
 *
 * The displayed name lives in the translation catalogues, keyed by the
 * category's code; the `name` on the record is the seed's fallback, not a
 * second display name. Two spellings of one category — "Cold cuts" in the
 * form, "Deli" thirty rows higher in bulk edit — is how a reader stops
 * finding their own records, so every screen that shows a category goes
 * through here.
 *
 * The `codes` branch of the shared `categories` catalogue carries every
 * module's seeded codes, equipment's included: a picker in the core shell
 * has no way to reach a module's own namespace. A module may mirror its
 * codes in its own namespace for screens that live inside the module
 * (equipment's `categories.codes` does, read through a static map so the
 * unused-key gate stays honest); mirrored values must agree with the
 * shared catalogue, and the one-source gate holds the two to it.
 */
export function categoryLabel(
  t: TranslateFn,
  code: string | null | undefined,
  name: string,
): string {
  if (!code) return name;
  return t(`categories:codes.${code}`, { defaultValue: name });
}

/**
 * `quantity` followed by its unit in the reader's language, or on its own.
 *
 * `rounding` is the unit's own step, and it decides how many decimal places
 * the number shows: without it this printed the string off the wire, so a
 * piece stored in `numeric(10,3)` read as "1.000 szt." — three decimals on a
 * unit that has none. A caller with the unit in hand passes `uom.rounding`;
 * one that only knows a symbol leaves it out and the value keeps the
 * precision it arrived with.
 */
export function formatQuantityLocalized(
  t: TranslateFn,
  quantity: number | string | null | undefined,
  symbol: string | null | undefined,
  rounding?: string | number | null,
): string {
  if (quantity === null || quantity === undefined || quantity === "") return "";
  const unit = unitLabel(t, symbol);
  const amount = formatQuantityValue(quantity, rounding);
  return unit ? `${amount} ${unit}` : amount;
}
