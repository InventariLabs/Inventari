/** One row a bulk operation refused, as every equipment batch endpoint reports it. */
export interface BulkRowError {
  item_id?: string;
  error?: string;
}

const MAX_NAMED = 3;

/**
 * Which rows a batch refused, and why — not just how many.
 *
 * "1 succeeded, 1 failed" over a few dozen assets is unreconstructable: the
 * reader cannot tell which asset stayed behind, so the whole batch has to be
 * repeated to find out. The backend already names the row and the reason;
 * this turns that into a sentence, naming the first few and counting the rest.
 */
export function bulkFailureDetail(
  errors: BulkRowError[],
  nameById: Map<string, string>,
  more: (count: number) => string,
): string | undefined {
  if (errors.length === 0) return undefined;

  const named = errors.slice(0, MAX_NAMED).map((failure) => {
    const name = failure.item_id ? nameById.get(failure.item_id) : undefined;
    const label = name ?? failure.item_id ?? "";
    return failure.error ? `${label} — ${failure.error}` : label;
  });

  const rest = errors.length - named.length;
  return rest > 0 ? [...named, more(rest)].join("; ") : named.join("; ");
}
