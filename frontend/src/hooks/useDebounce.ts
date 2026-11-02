import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Returns ``value`` after it has not changed for ``delay`` ms. Useful for
 * deferring expensive operations (e.g. API calls) until the user stops typing.
 *
 * @example
 * const [search, setSearch] = useState("");
 * const debouncedSearch = useDebounce(search, 300);
 * // queryKey includes debouncedSearch so we only fetch when typing pauses
 */
export function useDebounce<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    // The timer exists to publish a *changed* value; firing it for a value
    // already settled only schedules a bail-out update — one that lands
    // outside every test's act() and spams the run with act warnings.
    if (Object.is(value, debounced)) return;
    const timeout = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timeout);
  }, [value, delay, debounced]);

  return debounced;
}

/**
 * Defer a *call* until it stops being made for ``delay`` ms.
 *
 * The sibling of `useDebounce`, for the imperative case: a lookup fired
 * from an `onChange` rather than a value read during render. Every caller
 * that needed it had written the same ref-plus-clearTimeout by hand, and
 * none of them cancelled on unmount — the callback still ran, into a
 * component that had gone.
 *
 * The latest callback is read from a ref, so an inline arrow function does
 * not reset the timer on every render.
 */
export function useDebouncedCallback<A extends unknown[]>(
  callback: (...args: A) => void,
  delay = 300,
): (...args: A) => void {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    },
    [],
  );

  return useCallback(
    (...args: A) => {
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => callbackRef.current(...args), delay);
    },
    [delay],
  );
}
