import { useState, useCallback } from "react";
import { useAuthStore } from "@/store/authStore";
import { readJson, writeJson } from "@/lib/localStorage";

const STORAGE_KEY = "launcher_tile_order";

function getStorageKey(
  userId: string,
  orgId: string,
  category?: string,
): string {
  const base = `${STORAGE_KEY}:${orgId}:${userId}`;
  return category ? `${base}:${category}` : base;
}

function loadOrder(key: string): string[] | null {
  // readJson cannot vouch for the shape, so the guard stays here: a
  // hand-edited or stale value must not be handed to the sorter as-is.
  const parsed = readJson<unknown>(key, null);
  if (Array.isArray(parsed) && parsed.every((x) => typeof x === "string")) {
    return parsed as string[];
  }
  return null;
}

function saveOrder(key: string, order: string[]): void {
  writeJson(key, order);
}

/**
 * Sorts module names according to persisted order.
 * Unknown modules (newly enabled) are appended at the end.
 */
function applyOrder(modules: string[], savedOrder: string[]): string[] {
  const orderMap = new Map(savedOrder.map((id, idx) => [id, idx]));
  return [...modules].sort((a, b) => {
    const ia = orderMap.has(a) ? orderMap.get(a)! : Infinity;
    const ib = orderMap.has(b) ? orderMap.get(b)! : Infinity;
    return ia - ib;
  });
}

/**
 * Reads the arrangement the desktop sections persist, without owning it.
 *
 * The mobile grid cannot be reordered, so it has no business sorting by a rule
 * of its own: it reads the same store the sections write to, and shows the same
 * arrangement the same person made on a wider screen.
 */
export function useSavedTileOrder(): (
  moduleNames: string[],
  category: string,
) => string[] {
  const { user } = useAuthStore();
  const userId = user?.id ? String(user.id) : "anon";
  // The middle segment has read "default" since the key was invented: the
  // user record has never carried an organization id, so the old
  // `user.organization_id` read was the fallback branch and nothing else.
  // The constant keeps every stored key byte-for-byte what it was.
  const orgId = "default";

  return useCallback(
    (moduleNames: string[], category: string) => {
      const saved = loadOrder(getStorageKey(userId, orgId, category));
      return saved ? applyOrder(moduleNames, saved) : moduleNames;
    },
    [userId, orgId],
  );
}

export function useTileOrder(moduleNames: string[], category?: string) {
  const { user } = useAuthStore();
  const userId = user?.id ? String(user.id) : "anon";
  // The middle segment has read "default" since the key was invented: the
  // user record has never carried an organization id, so the old
  // `user.organization_id` read was the fallback branch and nothing else.
  // The constant keeps every stored key byte-for-byte what it was.
  const orgId = "default";
  const storageKey = getStorageKey(userId, orgId, category);

  const [order, setOrder] = useState<string[]>(() => {
    const saved = loadOrder(storageKey);
    if (!saved) return moduleNames;
    return applyOrder(moduleNames, saved);
  });

  const reorder = useCallback(
    (from: number, to: number) => {
      setOrder((prev) => {
        const next = [...prev];
        const [moved] = next.splice(from, 1);
        next.splice(to, 0, moved);
        saveOrder(storageKey, next);
        return next;
      });
    },
    [storageKey],
  );

  // Sync when moduleNames change (module activated/deactivated)
  const synced = applyOrder(moduleNames, order);

  return { order: synced, reorder };
}
