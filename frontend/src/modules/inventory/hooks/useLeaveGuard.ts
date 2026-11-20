import { useCallback, useEffect } from "react";

/**
 * Every way out of a form goes through `requestLeave`, so an edit in progress
 * is never lost without a word: when `isDirty`, the destination is handed to
 * `hold` (which asks the reader) instead of being followed. Escape closes the
 * same way. A module slot rendered inside the form can navigate away too,
 * which is why `requestLeave` is handed to it: the slot has no way to know
 * what the form is holding.
 */
export function useLeaveGuard(
  isDirty: boolean,
  onClose: () => void,
  hold: (go: () => void) => void,
) {
  const requestLeave = useCallback(
    (go: () => void) => (isDirty ? hold(go) : go()),
    [isDirty, hold],
  );

  const requestClose = useCallback(
    () => requestLeave(onClose),
    [requestLeave, onClose],
  );

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") requestClose();
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [requestClose]);

  return { requestLeave, requestClose };
}
