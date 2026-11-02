/**
 * Safe JSON access to `localStorage`.
 *
 * Every caller in this codebase had rewritten the same two guards: a
 * `try/catch` around `JSON.parse` (a corrupted or hand-edited value must not
 * take the page down) and one around `setItem` (quota exceeded, or Safari
 * private mode, where writes throw).
 *
 * Reading returns the fallback on *any* failure — missing key, unparseable
 * value, or storage being unavailable entirely. Writing fails silently,
 * because nothing here is important enough to interrupt the user for.
 *
 * Validation is deliberately left to the caller: `readJson` cannot know that
 * `["a", "b"]` is the right shape for a tile order, and a generic type
 * parameter is a claim, not a check. Callers that care validate what they get
 * back (see `useTileOrder`).
 */

export function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function writeJson(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Quota exceeded or storage unavailable — persistence is best-effort.
  }
}

export function removeKey(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // Same rationale as writeJson.
  }
}

/**
 * The session pair for values whose memory is deliberately per-tab: a
 * choice remembered for as long as the reader's flow lives, gone when the
 * tab closes. Same guards, same contract as the local pair above.
 */

export function readSessionJson<T>(key: string, fallback: T): T {
  try {
    const raw = sessionStorage.getItem(key);
    if (raw === null) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function writeSessionJson(key: string, value: unknown): void {
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Quota exceeded or storage unavailable — persistence is best-effort.
  }
}
