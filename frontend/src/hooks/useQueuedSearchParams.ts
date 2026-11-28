import { useCallback, useEffect } from "react";
import { useSearchParams } from "react-router-dom";

// The writes the screen has not rendered yet. One list for every caller: there
// is one address, and two hooks on one screen must build on each other.
let unrendered: string[] = [];

/**
 * The address's query parameters and the one safe way to edit them.
 *
 * Each write edits "the address as rendered" — the functional form of
 * `setSearchParams` included — and the router commits an address in a
 * transition: several controls cleared in one go, or a second chip tapped
 * while a busy phone is still rendering the first, would each start from the
 * same old address and the last write would undo the others. So a write here
 * builds on the writes the screen has not caught up with yet. They are
 * forgotten once it shows the last of them, or an address that is none of
 * them: somebody else navigated, and that address wins.
 *
 * `writeParams` replaces the entry on screen; `{ push: true }` adds one, for a
 * state Back should leave (a dialog).
 */
export function useQueuedSearchParams() {
  const [searchParams, setSearchParams] = useSearchParams();
  const rendered = searchParams.toString();
  useEffect(() => {
    const stillToCome =
      unrendered.includes(rendered) && unrendered.at(-1) !== rendered;
    if (!stillToCome) unrendered = [];
  }, [rendered]);
  const writeParams = useCallback(
    (edit: (next: URLSearchParams) => void, write?: { push?: boolean }) => {
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(unrendered.at(-1) ?? current);
          edit(next);
          unrendered.push(next.toString());
          return next;
        },
        { replace: !write?.push },
      );
    },
    [setSearchParams],
  );
  return [searchParams, writeParams] as const;
}
