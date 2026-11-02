import { useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { queryKeys } from "@/hooks/queries/keys";
import type { WarehouseDocument } from "../types";

const NAME_STALE_MS = 5 * 60_000;

/**
 * The document with a name on every line that has an item to name it by.
 *
 * A line created through the API may carry only `item_id`; the page used to
 * print a dash for it, so a worker executing a transfer could not tell which
 * record the line moves. The name is read from the item itself, once per
 * distinct item, and only for lines that lack one — a document whose lines
 * all carry names asks for nothing. An account that may not read items keeps
 * the dash: the refusal is not worth a toast on a screen that works.
 */
export function useDocumentLineNames(
  doc: WarehouseDocument | undefined,
): WarehouseDocument | undefined {
  const itemIds = useMemo(
    () => [
      ...new Set(
        (doc?.lines ?? []).flatMap((line) =>
          !line.name && line.item_id ? [line.item_id] : [],
        ),
      ),
    ],
    [doc],
  );

  const names = useQueries({
    queries: itemIds.map((itemId) => ({
      queryKey: [...queryKeys.documents.all, "line-item-name", itemId],
      queryFn: async () => {
        const response = await api.get<{ name?: string | null }>(
          `/items/${itemId}`,
        );
        return response.data.name ?? null;
      },
      staleTime: NAME_STALE_MS,
      retry: false,
    })),
    combine: (results) => results.map((result) => result.data ?? null),
  });

  return useMemo(() => {
    if (!doc || itemIds.length === 0) return doc;
    const byItem = new Map(itemIds.map((id, i) => [id, names[i]] as const));
    if (![...byItem.values()].some(Boolean)) return doc;
    return {
      ...doc,
      lines: doc.lines.map((line) =>
        !line.name && line.item_id && byItem.get(line.item_id)
          ? { ...line, name: byItem.get(line.item_id) ?? null }
          : line,
      ),
    };
  }, [doc, itemIds, names]);
}
