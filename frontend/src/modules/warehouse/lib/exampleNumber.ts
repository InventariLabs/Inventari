// The defaults `models/profile.py` and `document_types.py` hold. They stand in
// while the profile is still loading — and they are what an organization with
// no profile row is numbered by anyway, so the example never names a number
// from a second opinion about what "default" means.
const DEFAULT_NUMBERING_FORMAT = "{TYPE}/{YEAR}/{SEQ:03d}";
const DEFAULT_NUMBER_PADDING = 3;
/** The receipt's short code — `{TYPE}` writes it into every number of a fresh
 *  organization (`IN/2026/001`), in every language alike. */
const RECEIPT_SHORT_CODE = "IN";

interface NumberingShape {
  numberingFormat?: string;
  numberPadding?: number;
  /** The profile's own label for a receipt; blank means it named none. */
  receiptLabel?: string;
}

/**
 * The first number a receipt dated today gets under this numbering: what the
 * helps beside a number illustrate with, so an example is always a number the
 * profile actually produces.
 *
 * It mirrors `_build_prefix` and `generate_number` in
 * `document_numbering_service.py`: `{TYPE}` writes the receipt's short code,
 * `{TYPE_LABEL}` the profile's own label for it and the short code when it has
 * named none, `{YEAR}` and `{MONTH}` the date the document carries, and the
 * sequence padded to the profile's `number_padding`. Examples written into the
 * catalogs — "PZ/2026/0001", "Receipt/2026/001" — named numbers a profile
 * without that label, or with a `{MONTH}` in its format, never gives out.
 */
export function exampleReceiptNumber({
  numberingFormat,
  numberPadding,
  receiptLabel,
}: NumberingShape): string {
  const now = new Date();
  const prefix = (numberingFormat || DEFAULT_NUMBERING_FORMAT)
    // the shape only: the sequence digits are written after it, below
    .replace(/\{SEQ:\d+d\}/g, "")
    .replace(/\{ORG_PREFIX\}/g, "")
    .replace(/\{TYPE\}/g, RECEIPT_SHORT_CODE)
    .replace(/\{TYPE_LABEL\}/g, receiptLabel?.trim() || RECEIPT_SHORT_CODE)
    .replace(/\{YEAR\}/g, String(now.getFullYear()))
    .replace(/\{MONTH\}/g, String(now.getMonth() + 1).padStart(2, "0"));
  const digits = numberPadding ?? DEFAULT_NUMBER_PADDING;
  return `${prefix}${String(1).padStart(digits, "0")}`;
}
