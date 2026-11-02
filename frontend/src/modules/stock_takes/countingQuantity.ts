/**
 * What a person may type into a counting box, and what the number means.
 *
 * How finely a quantity may be stated is the unit's own business — `rounding`
 * on the UoM row — and the server asks that question at every door where
 * somebody types a quantity, this screen's save included. What the screen had
 * instead was a rule of its own, `parseInt` on the field, which turned 2.1 kg
 * into 2 kg before anything was sent and moved the difference across the
 * tolerance on the way. So the rule is mirrored here, on the same terms as
 * `validate_quantity_precision_async`, and asked before the save rather than
 * after the refusal.
 *
 * The box therefore holds text, not a number: a half-typed "2." is a keystroke
 * inside "2.1", and a box that reads itself back as a number blanks the dot
 * under the typist's finger.
 */

import { formatDecimalQty, stepText, toAmount } from "@/utils/formatters";

/**
 * A quantity as the box should show it: "2.100" off the wire reads "2.1".
 *
 * Every route into the box goes through here — seeding from the stock take,
 * putting a refused count back, and the step buttons — because a box that
 * shows the column's padding in one moment and 3.3499999999999996 in the
 * next is three different rules wearing one field.
 */
export function countedText(value: string | number | null | undefined): string {
  return value == null ? "" : formatDecimalQty(value, 3);
}

/** A count as typed: digits, with at most one decimal separator. */
const COUNT_TEXT = /^\d+([.,]\d*)?$/;

/**
 * The number a counting box holds, or `null` while it holds nothing.
 *
 * Nothing is not zero: an uncounted row and a row counted as none are
 * different answers, and every summary on the screen reads them apart.
 */
export function countedAmount(text: string | null | undefined): number | null {
  if (text == null) return null;
  const trimmed = text.trim();
  if (!COUNT_TEXT.test(trimmed)) return null;
  const amount = Number(trimmed.replace(",", "."));
  return Number.isFinite(amount) ? amount : null;
}

/**
 * Decimal places the unit leaves — three for a kilogram, none for a piece.
 *
 * Re-exported rather than defined here: the same rule decides what the
 * counting box accepts and how many places every screen prints, and two
 * copies of it would let a refusal and a display disagree about one unit.
 */
export { decimalsAllowedBy } from "@/utils/formatters";

/** Whether a count sits on the unit's step. A row without a unit asks nothing. */
export function fitsUnitStep(
  amount: number,
  rounding: string | number | null | undefined,
): boolean {
  const step = toAmount(stepText(rounding));
  if (step === null || step <= 0) return true;
  if (step >= 1) return Number.isInteger(amount);
  // The same comparison the server makes: a remainder within a thousandth of
  // the step counts as sitting on it, because 2.1 % 0.001 is not 0 in binary
  // floating point and never will be.
  const remainder = amount % step;
  const tolerance = step / 1000;
  return remainder <= tolerance || step - remainder <= tolerance;
}
