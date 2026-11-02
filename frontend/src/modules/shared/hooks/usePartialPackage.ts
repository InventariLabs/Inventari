import { useCallback } from "react";

import {
  findUom,
  getUomCategoryName,
  isCountedUom,
  useUoms,
} from "@/modules/shared/hooks/useUoms";
import type { UomCategory } from "@/types";
import { formatQuantityLocalized, unitLabel } from "@/lib/i18nHelpers";
import type { TranslateFn } from "@/types/i18n";
import { formatQuantityValue } from "@/utils/formatters";
import {
  partialPackage,
  partialPackageSentence,
  type PartialPackage,
  type PieceMeasure,
} from "@/utils/partialPackage";

/** The product card's per-piece measures, as an item or a template carries them. */
interface CardMeasures {
  weight_value?: number | null;
  weight_uom_id?: string | null;
  volume_value?: number | null;
  volume_uom_id?: string | null;
}

interface PartialPackageItem {
  quantity: string | number | null | undefined;
  /** A record's own unit, with its category. */
  uom?: { category_name?: string | null } | null;
  /** Or just the unit's id, for a payload that carries no category (a scan). */
  uomId?: string | null;
  template?: CardMeasures | null;
  /** What one piece measures, when the server has already resolved it. */
  pieceMeasure?: PieceMeasure | null;
}

/**
 * The partly-used-package answer for a record, with the card's unit symbols
 * resolved from the loaded catalogue. Weight wins when a card records both.
 * Returns `null` until the catalogue has loaded, so a row reads as it always
 * did for the moment before the symbol is known.
 */
export function usePartialPackage(): (
  item: PartialPackageItem,
) => PartialPackage | null {
  const { data: categories } = useUoms();
  return useCallback(
    (item) => {
      const pieceMeasure =
        item.pieceMeasure ?? cardMeasure(categories, item.template);
      return partialPackage({
        quantity: item.quantity,
        uom: item.uom ?? {
          category_name: getUomCategoryName(categories, item.uomId),
        },
        pieceMeasure,
      });
    },
    [categories],
  );
}

function measure(
  value: number | null | undefined,
  unit: { id: string; symbol: string } | null,
): PieceMeasure | null {
  return value && unit ? { value, symbol: unit.symbol, uomId: unit.id } : null;
}

/** What one piece weighs or holds, weight first, from a card's own fields. */
function cardMeasure(
  categories: UomCategory[] | undefined,
  card: CardMeasures | null | undefined,
): PieceMeasure | null {
  return (
    measure(card?.weight_value, findUom(categories, card?.weight_uom_id)) ??
    measure(card?.volume_value, findUom(categories, card?.volume_uom_id))
  );
}

/** What a card allows when somebody uses part of a package. */
export interface PartlyUsable {
  /** What one piece measures; null when the card cannot say what is left. */
  measure: PieceMeasure | null;
  packCounted: boolean;
}

/**
 * Whether a package of this card can be used partially, and how it is measured.
 *
 * A card counted in pieces with a recorded weight or volume asks how much is
 * left; a piece or pack without one can only be opened or finished; goods kept
 * in a measured unit have no package to open, and get `null`.
 */
export function usePartlyUsable(): (
  card: (CardMeasures & { uom_id?: string | null }) | null | undefined,
) => PartlyUsable | null {
  const { data: categories } = useUoms();
  return useCallback(
    (card) => {
      if (!card || !isCountedUom(categories, card.uom_id)) return null;
      return {
        packCounted: getUomCategoryName(categories, card.uom_id) !== "Unit",
        measure:
          getUomCategoryName(categories, card.uom_id) === "Unit"
            ? cardMeasure(categories, card)
            : null,
      };
    },
    [categories],
  );
}

/** What a record's quantity reads as on a screen that has room for one line. */
export function quantityText(
  t: TranslateFn,
  item: {
    quantity: string | number | null | undefined;
    uom?: { symbol?: string | null; rounding?: string | null } | null;
  },
  partial: PartialPackage | null,
): string {
  return partial
    ? partialPackageSentence(t, partial)
    : formatQuantityLocalized(
        t,
        item.quantity,
        item.uom?.symbol,
        item.uom?.rounding,
      );
}

/** The number and unit word a small badge carries: the remainder, or the quantity. */
export function badgeQuantity(
  t: TranslateFn,
  item: {
    quantity: string | number | null | undefined;
    uom?: { symbol?: string | null; rounding?: string | null } | null;
  },
  partial: PartialPackage | null,
): { number: string; unit: string } {
  return partial
    ? {
        number: formatQuantityValue(partial.amount),
        unit: unitLabel(t, partial.symbol),
      }
    : {
        number: formatQuantityValue(item.quantity, item.uom?.rounding),
        unit: unitLabel(t, item.uom?.symbol),
      };
}
