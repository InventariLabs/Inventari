import { useCallback, useEffect, useRef, useState } from "react";

/** The fields of `current` that differ from `base` — an edit in progress. */
export function changedSince<T extends object>(
  base: T,
  current: T,
): Partial<T> {
  const baseFields = base as Record<string, unknown>;
  return Object.fromEntries(
    Object.entries(current).filter(
      ([key, value]) =>
        JSON.stringify(value) !== JSON.stringify(baseFields[key]),
    ),
  ) as Partial<T>;
}

/**
 * Form fields over a stored record that is refetched under them. What the
 * reader has changed stays as typed; every other field takes the record's
 * answer.
 *
 * `read` turns the record into the fields and has to be a stable function.
 * `markSaved` takes the fields a save has stored: from then on only what is
 * typed past them counts as a change, so the refetch answers for the rest.
 */
export function useRecordFields<R, F extends object>(
  record: R,
  read: (record: R) => F,
) {
  const [fields, setFields] = useState(() => read(record));
  const baseRef = useRef(fields);

  useEffect(() => {
    const before = baseRef.current;
    const stored = read(record);
    baseRef.current = stored;
    setFields((prev) => ({ ...stored, ...changedSince(before, prev) }));
  }, [record, read]);

  const setField = useCallback(
    <K extends keyof F>(key: K, value: F[K]) =>
      setFields((prev) => ({ ...prev, [key]: value })),
    [],
  );
  const markSaved = useCallback((saved: F) => {
    baseRef.current = saved;
  }, []);

  return { fields, setField, markSaved };
}
