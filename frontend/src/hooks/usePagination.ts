import { useState, useEffect } from "react";

/**
 * Generic client-side pagination hook.
 * Works with any in-memory array — use `slice(skip, skip + limit)` to get the visible slice.
 *
 * @example
 * const { skip, limit, onPrev, onNext, reset } = usePagination(items.length, 10);
 * const visible = items.slice(skip, skip + limit);
 * // <Pagination skip={skip} limit={limit} total={items.length} onPrev={onPrev} onNext={onNext} />
 */
export function usePagination(total: number, limit: number) {
  const [skip, setSkip] = useState(0);

  // Reset to first page whenever the total changes (e.g. search filter applied)
  useEffect(() => {
    setSkip(0);
  }, [total]);

  const onPrev = () => setSkip((s) => Math.max(s - limit, 0));
  const onNext = () => setSkip((s) => (s + limit < total ? s + limit : s));
  const reset = () => setSkip(0);
  /** Jump to a zero-based page — what the shared Pagination's page picker asks for. */
  const setPage = (page: number) => setSkip(Math.max(page, 0) * limit);

  return { skip, limit, onPrev, onNext, reset, setPage };
}
