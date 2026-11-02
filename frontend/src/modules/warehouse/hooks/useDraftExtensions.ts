import { useCallback, useMemo, useRef } from "react";
import type { RegisterBeforeSubmit } from "@/lib/moduleRegistry";

/**
 * The callbacks other modules registered on a screen that builds a document
 * (Receive, Issue), run just before the screen saves or posts it.
 *
 * The document does not exist until the press that posts it, so a module's
 * own fields cannot be saved against it first. They are saved from here
 * instead, to the module's own API, and the module's pre-post check — asked
 * inside the posting — reads them back.
 */
export function useDraftExtensions() {
  const callbacks = useRef(new Set<() => void | Promise<void>>());

  const registerBeforeSubmit = useCallback<RegisterBeforeSubmit>((callback) => {
    callbacks.current.add(callback);
    return () => {
      callbacks.current.delete(callback);
    };
  }, []);

  const hasCallbacks = useCallback(() => callbacks.current.size > 0, []);

  /** In registration order; the first to throw stops the rest and the send. */
  const runBeforeSubmit = useCallback(async () => {
    for (const callback of [...callbacks.current]) await callback();
  }, []);

  return useMemo(
    () => ({ registerBeforeSubmit, hasCallbacks, runBeforeSubmit }),
    [registerBeforeSubmit, hasCallbacks, runBeforeSubmit],
  );
}
