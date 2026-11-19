import { useCallback, useRef, useState } from "react";
import type { RegisterBeforeSubmit } from "@/lib/moduleRegistry";

/**
 * What modules rendered inside the product sheet asked of it: callbacks to
 * run before the product's own save, and whether any of them holds typed
 * values nobody has saved yet (so closing the sheet asks first).
 */
export function useSheetExtensions() {
  const callbacks = useRef(new Set<() => void | Promise<void>>());
  const [dirty, reportDirty] = useState(false);

  const registerBeforeSubmit = useCallback<RegisterBeforeSubmit>((callback) => {
    callbacks.current.add(callback);
    return () => {
      callbacks.current.delete(callback);
    };
  }, []);

  /** In registration order; the first to throw stops the rest and the save. */
  const runBeforeSubmit = useCallback(async () => {
    for (const callback of [...callbacks.current]) await callback();
  }, []);

  return { registerBeforeSubmit, runBeforeSubmit, dirty, reportDirty };
}
