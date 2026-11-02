import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import type { TranslateFn } from "@/types/i18n";
import { toAmount } from "@/utils/formatters";

/** What one piece of a product weighs or holds, in the measure's own unit. */
export interface PieceMeasure {
  value: number;
  symbol: string;
  /** The measure's unit, for a request that has to name it. */
  uomId?: string;
}

/** The part of a record this answer reads. */
export interface PartialPackageSource {
  quantity: string | number | null | undefined;
  uom?: { category_name?: string | null } | null;
  /** What one piece measures, resolved by the caller from the product card. */
  pieceMeasure?: PieceMeasure | null;
}

export interface PartialPackage {
  /** What is left, in the measure's unit: 1.5 for 0.75 of a 2 kg piece. */
  amount: number;
  symbol: string;
  /** One piece's full size, the figure "left of" compares against. */
  size: PieceMeasure;
  /** Less than one piece is left; above one the answer is a total. */
  belowOnePiece: boolean;
}

/** The catalogue's counted-piece category; a pack is not a piece (ADR-015). */
const PIECE_CATEGORY = "Unit";

/**
 * A record kept in pieces that is partly used, restated in the unit its
 * product is weighed or measured in.
 *
 * 0.75 pcs on a 2 kg card is a three-quarters-full package, and the number
 * alone reads as a fault. The stored quantity does not change — the quant
 * view, the ledger and the exports sum quantities without a unit and rely on
 * the card's own — so this is only what the screen says. `null` for a whole
 * number of pieces, a record not counted in pieces and a card that records no
 * weight or volume per piece, all of which read as they always did.
 */
export function partialPackage(
  source: PartialPackageSource,
): PartialPackage | null {
  const quantity = toAmount(source.quantity);
  const size = source.pieceMeasure;
  if (quantity === null || quantity <= 0) return null;
  if (source.uom?.category_name !== PIECE_CATEGORY) return null;
  if (!size || !(size.value > 0) || !size.symbol) return null;
  if (Math.abs(quantity - Math.round(quantity)) < 1e-9) return null;
  return {
    // The columns carry three decimals; the product of two of them can carry
    // float noise beyond that.
    amount: Number((quantity * size.value).toFixed(4)),
    symbol: size.symbol,
    size,
    belowOnePiece: quantity < 1,
  };
}

/** "1.5 kg left of 2 kg", or "5 kg (2 kg each)" above one piece. */
export function partialPackageSentence(
  t: TranslateFn,
  pack: PartialPackage,
): string {
  const amount = formatQuantityLocalized(t, pack.amount, pack.symbol);
  const size = formatQuantityLocalized(t, pack.size.value, pack.size.symbol);
  return pack.belowOnePiece
    ? t("common:partialPackage.left", { left: amount, size })
    : t("common:partialPackage.several", { total: amount, size });
}

/** The full size beside a remainder that is shown on its own: "of 2 kg". */
export function partialPackageOfSize(
  t: TranslateFn,
  pack: PartialPackage,
): string {
  const size = formatQuantityLocalized(t, pack.size.value, pack.size.symbol);
  return pack.belowOnePiece
    ? t("common:partialPackage.of", { size })
    : t("common:partialPackage.each", { size });
}
