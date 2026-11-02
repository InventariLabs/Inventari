import { useCallback, useState } from "react";

/**
 * Paging through a list the server pages by the last row it handed out.
 *
 * Such a list has no "page 40": a page is reached from the one before it, by
 * the cursor that one carried. So the reader can go forward from where they
 * are and back to any page already seen — which is what the cursors kept here
 * are for — and nothing else.
 *
 * `question` is whatever the list is asked (its filters). When it changes the
 * pages and the cursors belong to a different question, so the reader starts
 * again from the first page rather than from a position that no longer exists.
 */
export function useKeysetPaging(question: unknown) {
  const key = JSON.stringify(question);
  const [asked, setAsked] = useState(key);
  const [page, setPage] = useState(0);
  // cursors[i] opens page i + 1; page 0 needs none.
  const [cursors, setCursors] = useState<string[]>([]);

  if (key !== asked) {
    setAsked(key);
    setPage(0);
    setCursors([]);
  }

  const goNext = useCallback(
    (nextCursor: string | null | undefined) => {
      if (!nextCursor) return;
      setCursors((seen) => {
        const kept = seen.slice(0, page);
        kept[page] = nextCursor;
        return kept;
      });
      setPage(page + 1);
    },
    [page],
  );

  const goPrev = useCallback(() => setPage((p) => Math.max(0, p - 1)), []);

  return {
    /** Zero-based index of the page on screen. */
    page,
    /** The cursor to ask for this page with; none for the first. */
    cursor: page === 0 ? undefined : cursors[page - 1],
    goNext,
    goPrev,
  };
}
