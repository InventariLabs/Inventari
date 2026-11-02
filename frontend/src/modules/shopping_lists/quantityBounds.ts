/**
 * The quantity contract the store holds, mirrored for the form.
 *
 * Source of truth: `app/schemas/validators.py` — `QUANTITY_MAX_DIGITS`,
 * `QUANTITY_SCALE` and `QUANTITY_MAX` there define the numeric(12, 3)
 * column every shopping-list quantity lands in, and the backend schemas
 * refuse anything above the ceiling with a sentence. The form may narrow
 * what it lets a person type (nothing non-positive, nothing past the
 * ceiling), never move a bound the backend does not hold.
 *
 * This is a mirror the frontend cannot import from Python, so
 * `npm run check:quantity-bounds` compares it — and `QUANTITY_STEP` in
 * `useUomPrecision.ts`, the form's floor — against the backend's constants.
 * Changing the column's shape in `validators.py` turns that gate red on
 * this line instead of silently leaving the form behind.
 */
export const QUANTITY_MAX = 999_999_999.999;
