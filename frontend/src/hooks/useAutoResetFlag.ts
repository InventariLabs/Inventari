import { useEffect, useRef, useState } from "react";

/**
 * A boolean that resets itself after a delay — the "Copied" badge and its
 * siblings.
 *
 * The reset is delayed work on the global timer queue, and the arm call
 * comes from an event handler, so nobody owns the id: a dialog that closes
 * inside the window used to fire its state set on a dead component, which
 * vitest reports as an unhandled error after teardown — green tests, exit 1.
 * The id lives in a ref and unmount takes the timer back.
 */
export function useAutoResetFlag(resetAfterMs: number): [boolean, () => void] {
  const [on, setOn] = useState(false);
  const timerRef = useRef<number | null>(null);

  // Runs whether or not arm() ever fired: the window may be pending while
  // the component never mounts its other cleanups.
  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, []);

  const arm = () => {
    setOn(true);
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
    }
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      setOn(false);
    }, resetAfterMs);
  };

  return [on, arm];
}
