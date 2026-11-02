/**
 * The day a record is judged by: its batch date or, if earlier, the use-by
 * given when it was opened. The server works it out; a record from an older
 * answer that lacks it falls back to the batch date.
 */
export function effectiveExpiry(item: {
  expiry_date?: string | null;
  effective_expiry_date?: string | null;
}): string | null {
  return item.effective_expiry_date ?? item.expiry_date ?? null;
}
