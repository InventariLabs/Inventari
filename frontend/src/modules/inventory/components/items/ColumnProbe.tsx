import { useEffect } from "react";
import type { Item } from "@/types";

interface ColumnProbeProps {
  columnKey: string;
  useHasValues: (items: Item[]) => boolean | undefined;
  items: Item[];
  onResult: (key: string, hasValues: boolean) => void;
}

/**
 * Asks one module column whether the current page holds anything for it.
 *
 * It exists as a component rather than a call in the table because the answer
 * comes from a hook: a component per contributor keeps each module's hooks in
 * their own, stable order however the contributor list changes.
 */
export function ColumnProbe({
  columnKey,
  useHasValues,
  items,
  onResult,
}: ColumnProbeProps) {
  const hasValues = useHasValues(items);

  useEffect(() => {
    if (hasValues !== undefined) onResult(columnKey, hasValues);
  }, [columnKey, hasValues, onResult]);

  return null;
}
