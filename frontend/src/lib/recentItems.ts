/**
 * recentItems.ts — Cross-module recently visited items tracker.
 *
 * Storage: localStorage, key `inventari:recent:{userId}:{orgId}`.
 * Multi-tenant isolation: scoped per user AND per organization.
 * Max 20 items (FIFO). Deduplication by `id`.
 *
 * Privacy: Never store sensitive data. Titles are item names only.
 * The list leaves with the identity that made it: `authStore` calls
 * `clearRecentItems` on logout and on a session that ends without one, so a
 * shared device does not hand the next holder a list of the previous one's
 * records.
 */

import { readJson, removeKey, writeJson } from "@/lib/localStorage";

export interface RecentItem {
  id: string;
  /** Display name (item name, asset name, recipe title, etc.). */
  title: string;
  /** Source module, e.g. 'inventory' | 'equipment' | 'recipes'. */
  module: string;
  /** Full route to navigate to, e.g. '/inventory/items/abc-123'. */
  path: string;
  /** Lucide icon name (string) for display. Optional. */
  icon?: string;
  /** Timestamp when the item was visited (Date.now()). */
  timestamp: number;
}

const MAX_RECENT_ITEMS = 20;

/**
 * The organization segment every writer and reader of the list uses. It has
 * read "default" since the key was invented: the user record has never
 * carried an organization id. The list is cleared with the identity that
 * made it (see above).
 */
export const RECENT_ITEMS_SCOPE = "default";

function storageKey(userId: string, orgId: string): string {
  return `inventari:recent:${userId}:${orgId}`;
}

/**
 * Records a visited item for the given user+org context.
 * Deduplicates by `id` and evicts oldest entries beyond MAX_RECENT_ITEMS.
 */
export function addRecentItem(
  item: RecentItem,
  userId: string,
  orgId: string,
): void {
  const key = storageKey(userId, orgId);
  const existing = getRecentItems(userId, orgId);

  // Remove any previous entry with the same id (dedup)
  const filtered = existing.filter((r) => r.id !== item.id);

  // Prepend the new item (most recent first)
  const updated = [{ ...item, timestamp: Date.now() }, ...filtered].slice(
    0,
    MAX_RECENT_ITEMS,
  );

  writeJson(key, updated);
}

/**
 * Returns the list of recently visited items for the given user+org,
 * sorted by most recent first.
 */
export function getRecentItems(userId: string, orgId: string): RecentItem[] {
  const parsed = readJson<unknown>(storageKey(userId, orgId), []);
  return Array.isArray(parsed) ? (parsed as RecentItem[]) : [];
}

/**
 * Clears all recent item entries for a given user across all organizations.
 * Called by `authStore` on both teardown paths — an explicit logout and a
 * session that simply ended.
 */
export function clearRecentItems(userId: string): void {
  const prefix = `inventari:recent:${userId}:`;
  const keysToRemove: string[] = [];

  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith(prefix)) {
        keysToRemove.push(k);
      }
    }
    keysToRemove.forEach(removeKey);
  } catch {
    // localStorage unavailable — fail silently
  }
}
