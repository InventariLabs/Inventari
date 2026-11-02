import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  installStaleChunkRecovery,
  isStaleChunkError,
  RELOAD_GUARD_KEY,
  RELOAD_GUARD_MS,
} from "./staleChunk";

function preloadError(payload: unknown): Event {
  const event = new Event("vite:preloadError", { cancelable: true });
  (event as Event & { payload?: unknown }).payload = payload;
  return event;
}

describe("isStaleChunkError", () => {
  it.each([
    "Failed to fetch dynamically imported module: https://x/assets/Launcher-abc.js",
    "error loading dynamically imported module: https://x/assets/Launcher-abc.js",
    "Importing a module script failed.",
    "Unable to preload CSS for /assets/Launcher-abc.css",
  ])("recognises %s", (message) => {
    expect(isStaleChunkError(new TypeError(message))).toBe(true);
  });

  it("leaves every other error alone", () => {
    expect(isStaleChunkError(new Error("planted: the screen broke"))).toBe(
      false,
    );
    expect(isStaleChunkError("a string")).toBe(false);
    expect(isStaleChunkError(null)).toBe(false);
  });
});

describe("installStaleChunkRecovery", () => {
  const reload = vi.fn();
  let uninstall: () => void;

  beforeEach(() => {
    vi.useFakeTimers();
    sessionStorage.clear();
    reload.mockClear();
    uninstall = installStaleChunkRecovery(reload);
  });
  afterEach(() => {
    uninstall();
    vi.useRealTimers();
  });

  it("reloads once when a lazy chunk fails to load", () => {
    window.dispatchEvent(
      preloadError(
        new TypeError("Failed to fetch dynamically imported module"),
      ),
    );
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("does not reload again while the guard is live, so a chunk that stays missing cannot loop", () => {
    const first = preloadError(
      new TypeError("Failed to fetch dynamically imported module"),
    );
    const second = preloadError(
      new TypeError("Failed to fetch dynamically imported module"),
    );
    window.dispatchEvent(first);
    window.dispatchEvent(second);
    expect(reload).toHaveBeenCalledTimes(1);
    // The second failure is left to the error screen: the event is not
    // swallowed, so the import still rejects.
    expect(second.defaultPrevented).toBe(false);
  });

  it("reloads again after the guard window, for a later deploy", () => {
    window.dispatchEvent(
      preloadError(new TypeError("Importing a module script failed.")),
    );
    vi.advanceTimersByTime(RELOAD_GUARD_MS + 1);
    window.dispatchEvent(
      preloadError(new TypeError("Importing a module script failed.")),
    );
    expect(reload).toHaveBeenCalledTimes(2);
  });

  it("does not reload when the guard cannot be stored", () => {
    const set = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => {
        throw new Error("storage blocked");
      });
    window.dispatchEvent(
      preloadError(new TypeError("Importing a module script failed.")),
    );
    expect(reload).not.toHaveBeenCalled();
    set.mockRestore();
  });

  it("keeps the timestamp under one key", () => {
    window.dispatchEvent(
      preloadError(new TypeError("Importing a module script failed.")),
    );
    expect(sessionStorage.getItem(RELOAD_GUARD_KEY)).not.toBeNull();
  });
});

describe("installStaleChunkRecovery — with no reload given", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reloads the browser page when a lazy chunk fails to load", () => {
    const reload = vi.fn();
    vi.stubGlobal("location", { ...window.location, reload });
    const uninstall = installStaleChunkRecovery();

    window.dispatchEvent(
      preloadError(
        new TypeError("Failed to fetch dynamically imported module"),
      ),
    );

    expect(reload).toHaveBeenCalledTimes(1);
    uninstall();
  });
});
