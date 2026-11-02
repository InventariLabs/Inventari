import { useCallback, useState } from "react";
import { readJson, writeJson } from "@/lib/localStorage";

/**
 * `useState` backed by `localStorage`.
 *
 * For values a component *renders* — the state and the stored copy stay in
 * step, and the initial read happens lazily so it costs nothing on re-render.
 *
 * Not every `localStorage` caller wants this. Most of them
 * (`lib/recentItems.ts`, `UomSelect`, `useTileOrder`) read and write
 * imperatively inside event handlers, with no component state involved; those
 * use `readJson` / `writeJson` from `@/lib/localStorage` directly. Reach for
 * the hook only when the value drives rendering.
 */
export function useLocalStorage<T>(
  key: string,
  initialValue: T,
): [T, (value: T | ((prev: T) => T)) => void] {
  const [stored, setStored] = useState<T>(() => readJson(key, initialValue));

  const setValue = useCallback(
    (value: T | ((prev: T) => T)) => {
      setStored((prev) => {
        const next =
          typeof value === "function" ? (value as (p: T) => T)(prev) : value;
        writeJson(key, next);
        return next;
      });
    },
    [key],
  );

  return [stored, setValue];
}
