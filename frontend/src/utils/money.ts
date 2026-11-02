/**
 * Line money, computed the way the backend computes it.
 *
 * Five screens were doing this arithmetic in floats and each in its own
 * order, so a form and the document it was about to create disagreed by a
 * cent — and on the purchase-order form the printed net plus the printed VAT
 * did not add up to the printed gross, because all three were rounded
 * separately off unrounded running totals.
 *
 * Two rules, both taken from `app/core/money.py`, which is what actually
 * stores the numbers:
 *
 * - **Round each line, then add.** The printed net and the printed tax have
 *   to be the ones that add up to the printed gross. Adding first and
 *   rounding the total gives a different answer whenever a line's own tax
 *   lands on a half.
 * - **Half away from zero.** `toFixed` rounds the binary float, and not
 *   every half survives that representation: 2.675 is stored a hair under
 *   one and goes down to "2.67", where the backend stores 2.68. Every amount
 *   in this application rounds a half upwards.
 */

/** Round half away from zero, on the decimal the digits actually spell. */
export function roundHalfUp(value: number, places = 2): number {
  if (!Number.isFinite(value)) return 0;
  const factor = 10 ** places;
  // The epsilon corrects for the binary representation falling a hair under
  // a half — the reason `toFixed` disagrees with a decimal calculator.
  const scaled = value * factor;
  const nudged =
    scaled + (scaled >= 0 ? 1 : -1) * Number.EPSILON * Math.abs(scaled);
  return (Math.sign(nudged) * Math.round(Math.abs(nudged))) / factor;
}

export interface LineAmounts {
  net: number;
  tax: number;
  gross: number;
}

/** What one priced line is worth: before tax, the tax, and together. */
export function lineAmounts(
  quantity: number | string | null | undefined,
  unitPrice: number | string | null | undefined,
  taxRatePct: number | string | null | undefined,
): LineAmounts {
  const qty = Number(quantity) || 0;
  const price = Number(unitPrice) || 0;
  const rate = Number(taxRatePct) || 0;
  const net = roundHalfUp(qty * price);
  const tax = roundHalfUp((qty * price * rate) / 100);
  return { net, tax, gross: net + tax };
}

/** The same three figures, summed over a set of lines. */
export function totalAmounts(
  lines: Array<{
    quantity: number | string | null | undefined;
    unit_price: number | string | null | undefined;
    tax_rate: number | string | null | undefined;
  }>,
): LineAmounts {
  let net = 0;
  let tax = 0;
  for (const line of lines) {
    const amounts = lineAmounts(line.quantity, line.unit_price, line.tax_rate);
    net += amounts.net;
    tax += amounts.tax;
  }
  net = roundHalfUp(net);
  tax = roundHalfUp(tax);
  return { net, tax, gross: net + tax };
}

export interface RateAmounts extends LineAmounts {
  rate: number;
}

/**
 * Net and tax summed per tax rate, highest rate first — `amounts_by_rate`
 * in `app/core/money.py`. A line without a rate or a net belongs to no rate.
 */
export function amountsByRate(
  lines: Array<{
    tax_rate: number | string | null | undefined;
    line_value: number | string | null | undefined;
    line_tax: number | string | null | undefined;
  }>,
): RateAmounts[] {
  const sums = new Map<number, { net: number; tax: number }>();
  for (const line of lines) {
    if (line.tax_rate == null || line.tax_rate === "") continue;
    if (line.line_value == null || line.line_value === "") continue;
    const rate = roundHalfUp(Number(line.tax_rate));
    const prior = sums.get(rate) ?? { net: 0, tax: 0 };
    sums.set(rate, {
      net: prior.net + Number(line.line_value),
      tax: prior.tax + (Number(line.line_tax) || 0),
    });
  }
  return [...sums.entries()]
    .sort(([a], [b]) => b - a)
    .map(([rate, sum]) => {
      const net = roundHalfUp(sum.net);
      const tax = roundHalfUp(sum.tax);
      return { rate, net, tax, gross: roundHalfUp(net + tax) };
    });
}
