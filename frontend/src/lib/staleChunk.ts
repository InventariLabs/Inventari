/**
 * A lazy route whose chunk cannot be fetched.
 *
 * Every deploy renames the hashed files under `/assets`. A tab opened before
 * the deploy still holds the old names, and a restart can drop a request for
 * a moment too, so `import()` rejects with "Failed to fetch dynamically
 * imported module" and the reader met a raw TypeError on screen.
 *
 * The bundler dispatches `vite:preloadError` for every dynamic import that
 * fails, so one listener covers every `lazy()` in the app. It reloads once —
 * the reload picks up the new `index.html` and its new names — and a guard
 * keeps a chunk that is really gone from turning that into a reload loop.
 * The failure that outlives the guard reaches the error screens, which
 * recognise it with `isStaleChunkError` and say what happened in words.
 */

export const RELOAD_GUARD_KEY = "inventari.staleChunkReloadAt";

/** A second failure within this window is shown, not retried. */
export const RELOAD_GUARD_MS = 30_000;

// Chromium, Firefox and Safari word the same failure three ways; the CSS
// wording is the bundler's own, for a stylesheet that rides with a chunk.
const STALE_CHUNK_MESSAGE =
  /Failed to fetch dynamically imported module|error loading dynamically imported module|Importing a module script failed|Unable to preload CSS/i;

export function isStaleChunkError(error: unknown): boolean {
  // Matched on the browser's own wording, never shown: the reader gets a
  // translated sentence instead.
  return error instanceof Error && STALE_CHUNK_MESSAGE.test(String(error));
}

/** True when this tab may reload now; records the attempt either way it can. */
function claimReload(): boolean {
  try {
    const last = Number(sessionStorage.getItem(RELOAD_GUARD_KEY) ?? 0);
    if (Date.now() - last < RELOAD_GUARD_MS) return false;
    sessionStorage.setItem(RELOAD_GUARD_KEY, String(Date.now()));
    return true;
  } catch {
    // Without a place for the guard a reload could repeat forever.
    return false;
  }
}

/** Returns the function that removes the listener again. */
export function installStaleChunkRecovery(
  reload: () => void = () => window.location.reload(),
): () => void {
  const onPreloadError = (event: Event) => {
    const { payload } = event as Event & { payload?: unknown };
    if (isStaleChunkError(payload) && claimReload()) reload();
  };
  window.addEventListener("vite:preloadError", onPreloadError);
  return () => window.removeEventListener("vite:preloadError", onPreloadError);
}
