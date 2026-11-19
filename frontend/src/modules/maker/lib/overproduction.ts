/**
 * How far above its plan a run may close before the person is asked to say
 * so: a quarter. A 10 kg batch finished as 12 kg is a good day; as 59 kg it
 * is almost certainly a typo, and the ingredients stay as planned either way.
 */
const OVERPRODUCTION_SHARE = 0.25;

/**
 * The quantity a typed total puts above the plan, or `null` when the total
 * is empty, not a number, or within the allowed share of the plan.
 */
export function overproductionExtra(
  planned: string | number,
  typed: string,
): number | null {
  const plan = Number(planned);
  const actual = typed.trim() === "" ? NaN : Number(typed);
  if (!Number.isFinite(plan) || !Number.isFinite(actual) || plan <= 0) {
    return null;
  }
  return actual > plan * (1 + OVERPRODUCTION_SHARE) ? actual - plan : null;
}
