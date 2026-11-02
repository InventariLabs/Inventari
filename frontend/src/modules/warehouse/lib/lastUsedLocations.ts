import { readJson, writeJson } from "@/lib/localStorage";

/**
 * remember the last used source/target location per document type,
 * so a fresh document form can prefill them. Stored in localStorage —
 * a convenience, not authoritative state; unknown/deleted location ids are
 * ignored by the caller.
 */

const STORAGE_KEY = "warehouse:lastUsedLocations";

interface LastUsedEntry {
  source?: string;
  target?: string;
}

type LastUsedMap = Partial<Record<string, LastUsedEntry>>;

export function readLastUsedLocations(): LastUsedMap {
  // `readJson` already answers a missing key, a corrupted value and storage
  // being unavailable with the fallback; the shape check stays here because
  // a generic parameter is a claim, not one.
  const stored = readJson<unknown>(STORAGE_KEY, {});
  if (typeof stored !== "object" || stored === null || Array.isArray(stored)) {
    return {};
  }
  return stored as LastUsedMap;
}

export function rememberLastUsedLocations(
  docType: string,
  sourceLocationId: string,
  targetLocationId: string,
): void {
  if (!sourceLocationId && !targetLocationId) return;
  const map = readLastUsedLocations();
  map[docType] = {
    ...(sourceLocationId ? { source: sourceLocationId } : {}),
    ...(targetLocationId ? { target: targetLocationId } : {}),
  };
  // A failed write is a prefill that will not happen, which `writeJson`
  // swallows on purpose.
  writeJson(STORAGE_KEY, map);
}
