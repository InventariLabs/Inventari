/**
 * Downloads a Blob as a file by creating a temporary anchor element.
 */
export const downloadBlob = (blob: Blob, filename: string): void => {
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.URL.revokeObjectURL(url);
};

/**
 * How many days from today until the day this value names.
 *
 * An expiry is a day printed on a carton, not an instant, so both sides of
 * the subtraction have to be the same kind of thing. `new Date("2026-09-01")`
 * is midnight UTC while `setHours(0,0,0,0)` is midnight where the reader is,
 * and the offset between them leaked into the day count: east of Greenwich a
 * carton due in exactly seven days counted as eight and dropped out of
 * "expiring soon", west of it today's carton counted as already expired.
 *
 * Reading the calendar day off the front of the string keeps a plain date and
 * a full timestamp meaning the same thing. `null` when the value names no day
 * at all.
 *
 * Exported because the equipment warranty badge asks the same question — how
 * many days away is the day this value names — and had grown its own, UTC
 * midnight and `Math.ceil` included.
 */
export const daysUntil = (value: string): number | null => {
  const named = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!named) return null;
  const [, year, month, day] = named;
  const expiry = new Date(Number(year), Number(month) - 1, Number(day));
  if (Number.isNaN(expiry.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  // Rounded, not ceiled: the clocks change twice a year and one of those
  // days is 23 hours long.
  return Math.round(
    (expiry.getTime() - today.getTime()) / (1000 * 60 * 60 * 24),
  );
};

/**
 * Checks if a date is within the next 7 days.
 */
export const isExpiringSoon = (
  expiryDate: string | null | undefined,
): boolean => {
  if (!expiryDate) return false;
  const days = daysUntil(expiryDate);
  return days !== null && days <= 7 && days >= 0;
};

/**
 * Checks if a date is in the past.
 */
export const isExpired = (expiryDate: string | null | undefined): boolean => {
  if (!expiryDate) return false;
  const days = daysUntil(expiryDate);
  return days !== null && days < 0;
};

/**
 * The three states an expiry date can be in, in one value.
 *
 * Item rows and item cards both colour the expiry badge from this state, and
 * both expose it as `data-expiry-state` so a test can assert the warning
 * without reading colour classes or a locale-formatted date.
 */
export type ExpiryState = "expired" | "expiring" | "ok";

export const getExpiryState = (
  expiryDate: string | null | undefined,
): ExpiryState => {
  if (isExpired(expiryDate)) return "expired";
  if (isExpiringSoon(expiryDate)) return "expiring";
  return "ok";
};

/**
 * STM prefix constant for labels.
 */
/**
 * Builds a full location path from storage name and optional shelf location.
 * Example: "Fridge" or with shelf: "Fridge → Second shelf"
 */
interface LocationPathOptions {
  name: string;
  shelfLocation?: string | null;
  separator?: string;
  maxParts?: number;
}

const buildLocationPath = (options: LocationPathOptions): string => {
  const { name, shelfLocation, separator = " → " } = options;

  if (shelfLocation) {
    return `${name}${separator}${shelfLocation}`;
  }

  return name;
};

/**
 * The one separator a location path is written with.
 *
 * The backend composes `full_path` with it (`core/location_path.py`), so a
 * screen that joins segments itself has to use the same one — two shelves
 * called "Top" are told apart by the path, and a path in two dialects reads
 * as two different places. It is not an arrow: "→" says where a document's
 * goods went, and a path written with it read as a journey.
 */
export const LOCATION_PATH_SEPARATOR = " › ";

/**
 * The path to show *under* a location's own name, or nothing.
 *
 * A root storage's path is its own name, and printing it twice under itself
 * is noise rather than context. Three pickers carried this condition inline,
 * which is three chances for them to drift apart.
 */
export const locationPathBelowName = (storage: {
  name: string;
  full_path?: string | null;
}): string | undefined =>
  storage.full_path && storage.full_path !== storage.name
    ? storage.full_path
    : undefined;

/**
 * A location path cut into the place itself and the road to it.
 *
 * The leaf is the part that tells two shelves apart ("Shelf A - Bottom" and
 * "Shelf B - Top" under the same warehouse), so a cell too narrow for the whole
 * path prints it first and lets only the road be cut short.
 */
export const splitLocationPath = (
  path: string,
): { leaf: string; parents: string | null } => {
  const cut = path.lastIndexOf(LOCATION_PATH_SEPARATOR);
  if (cut === -1) return { leaf: path, parents: null };
  return {
    leaf: path.slice(cut + LOCATION_PATH_SEPARATOR.length),
    parents: path.slice(0, cut),
  };
};

/** The shape any storage-like record must have to sit on a path. */
export interface LocationPathNode {
  id?: string;
  name: string;
  parent_id?: string | null;
  full_path?: string | null;
}

/**
 * Walk a node's ancestors and join them into a path.
 *
 * Only reached when the record carries no backend `full_path` — the list
 * endpoint sends one (`StorageLocationSummary`), but several screens hold a
 * shape that does not, and a leaf name alone is ambiguous: two shelves called
 * "Top" in different warehouses read as the same place. Cycle-guarded, because
 * legacy rows can point at each other.
 */
const buildAncestorPath = (
  storage: LocationPathNode,
  allStorages: readonly LocationPathNode[],
  separator: string,
): string => {
  const byId = new Map(
    allStorages.filter((s) => s.id).map((s) => [s.id as string, s]),
  );
  const parts = [storage.name];
  const seen = new Set<string>(storage.id ? [storage.id] : []);
  let parentId = storage.parent_id;

  while (parentId && !seen.has(parentId)) {
    seen.add(parentId);
    const parent = byId.get(parentId);
    if (!parent) break;
    parts.unshift(parent.name);
    parentId = parent.parent_id;
  }

  return parts.join(separator);
};

/**
 * Gets the full location path for an item given its storage location and optional shelf.
 * Uses backend-computed `full_path` when available, otherwise walks `parent_id`
 * through `allStorages`, and falls back to the bare name when neither is there.
 */
export const getStorageLocationPath = (
  storage: LocationPathNode | null | undefined,
  shelfLocation?: string | null,
  options?: { separator?: string; maxParts?: number },
  allStorages?: readonly LocationPathNode[],
): string => {
  if (!storage) return "";

  const separator = options?.separator ?? LOCATION_PATH_SEPARATOR;

  // Use backend-computed path when available (most reliable)
  if (storage.full_path) {
    return shelfLocation
      ? `${storage.full_path}${separator}${shelfLocation}`
      : storage.full_path;
  }

  // No backend path: rebuild it from the list the caller already holds.
  if (allStorages?.length && storage.parent_id) {
    const path = buildAncestorPath(storage, allStorages, separator);
    return shelfLocation ? `${path}${separator}${shelfLocation}` : path;
  }

  // Fallback: use storage name
  return buildLocationPath({
    name: storage.name,
    shelfLocation,
    ...options,
  });
};

// Date formatters moved to `utils/formatters.ts` (dedup 6.4). Re-exported here
// because a large number of call sites import them from this module.
export {
  formatDate,
  formatDateMedium,
  formatDateRange,
  formatDateTime,
  formatDateTimePrecise,
  formatMonthName,
  formatTime,
} from "@/utils/formatters";
