import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { useThemeStore, watchSystemTheme } from "./themeStore";

/** Stand-in for `prefers-color-scheme`, with a way to flip it mid-test. */
function stubPrefersColorScheme(dark: boolean) {
  const listeners = new Set<(e: MediaQueryListEvent) => void>();
  let matches = dark;
  const mql = {
    get matches() {
      return matches;
    },
    media: "(prefers-color-scheme: dark)",
    addEventListener: (_: string, fn: (e: MediaQueryListEvent) => void) =>
      listeners.add(fn),
    removeEventListener: (_: string, fn: (e: MediaQueryListEvent) => void) =>
      listeners.delete(fn),
  };
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => mql),
  );
  return {
    flip(next: boolean) {
      matches = next;
      listeners.forEach((fn) => fn({ matches: next } as MediaQueryListEvent));
    },
    listenerCount: () => listeners.size,
  };
}

describe("useThemeStore", () => {
  beforeEach(() => {
    document.documentElement.classList.remove("dark");
    localStorage.removeItem("inventari-theme");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("follows the system by default", () => {
    useThemeStore.setState({ mode: "system" });
    expect(useThemeStore.getState().mode).toBe("system");
  });

  it("resolves the system preference to a dark interface", () => {
    stubPrefersColorScheme(true);
    useThemeStore.getState().setMode("system");

    expect(useThemeStore.getState().resolved).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("resolves the system preference to a light interface", () => {
    stubPrefersColorScheme(false);
    useThemeStore.getState().setMode("system");

    expect(useThemeStore.getState().resolved).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("lets an explicit choice override a dark system", () => {
    stubPrefersColorScheme(true);
    useThemeStore.getState().setMode("light");

    expect(useThemeStore.getState().resolved).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("sets mode to dark and adds class to html", () => {
    useThemeStore.getState().setMode("dark");
    expect(useThemeStore.getState().mode).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("sets mode to light and removes dark class", () => {
    useThemeStore.getState().setMode("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    useThemeStore.getState().setMode("light");
    expect(useThemeStore.getState().mode).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("persists mode to localStorage", () => {
    useThemeStore.getState().setMode("dark");
    const stored = JSON.parse(localStorage.getItem("inventari-theme") || "{}");
    expect(stored.state?.mode).toBe("dark");
  });

  it("does not persist the resolved theme — the system may have changed since", () => {
    useThemeStore.getState().setMode("dark");
    const stored = JSON.parse(localStorage.getItem("inventari-theme") || "{}");
    expect(stored.state?.resolved).toBeUndefined();
  });

  it("paints dark on a first visit to a dark system, with nothing stored", () => {
    // The case the whole point rests on: a visitor whose desktop is dark and
    // who has never touched the toggle. Nothing in localStorage, so rehydration
    // has to resolve "system" rather than leave the default light paint.
    stubPrefersColorScheme(true);
    localStorage.removeItem("inventari-theme");
    useThemeStore.setState({ mode: "system", resolved: "light" });
    document.documentElement.classList.remove("dark");

    useThemeStore.persist.rehydrate();

    expect(useThemeStore.getState().resolved).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("restores mode from localStorage on init", () => {
    localStorage.setItem(
      "inventari-theme",
      JSON.stringify({ state: { mode: "dark" }, version: 0 }),
    );
    useThemeStore.persist.rehydrate();
    expect(useThemeStore.getState().mode).toBe("dark");
  });

  it("resolves a stored dark mode at creation, not only after an explicit toggle", async () => {
    // Regression: with a synchronous localStorage zustand rehydrates
    // the store while create() is still running, so the old rehydration
    // callback's `useThemeStore.setState` hit the temporal dead zone and
    // threw a ReferenceError persist swallowed — html got .dark but resolved
    // stayed "light" and the profile palette never remapped. Importing the
    // module fresh exercises that creation-time path on the real store.
    vi.resetModules();
    localStorage.setItem(
      "inventari-theme",
      JSON.stringify({ state: { mode: "dark" }, version: 0 }),
    );
    document.documentElement.classList.remove("dark");

    const { useThemeStore: freshStore } = await import("./themeStore");

    expect(freshStore.getState().mode).toBe("dark");
    expect(freshStore.getState().resolved).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("surfaces a failed rehydration in the console instead of swallowing it", () => {
    // persist reports a failed hydration to the callback's `error` argument;
    // the old code read only `state`, so a broken storage value vanished
    // without a trace.
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    localStorage.setItem("inventari-theme", "{ not json");
    try {
      useThemeStore.persist.rehydrate();

      expect(errorSpy).toHaveBeenCalledWith(
        expect.stringContaining("theme rehydration failed"),
        expect.anything(),
      );
    } finally {
      errorSpy.mockRestore();
      localStorage.removeItem("inventari-theme");
    }
  });
});

describe("watchSystemTheme", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("follows the system flipping to dark while on 'system'", () => {
    const system = stubPrefersColorScheme(false);
    const stop = watchSystemTheme();
    useThemeStore.getState().setMode("system");

    system.flip(true);

    expect(useThemeStore.getState().resolved).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    stop();
  });

  it("ignores the system once the user has chosen a theme", () => {
    const system = stubPrefersColorScheme(false);
    const stop = watchSystemTheme();
    useThemeStore.getState().setMode("light");

    system.flip(true);

    expect(useThemeStore.getState().resolved).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    stop();
  });

  it("stops listening when told to", () => {
    const system = stubPrefersColorScheme(false);
    const stop = watchSystemTheme();
    expect(system.listenerCount()).toBe(1);

    stop();

    expect(system.listenerCount()).toBe(0);
  });

  it("does nothing, and can still be stopped, where the browser has no matchMedia", () => {
    vi.stubGlobal("matchMedia", undefined);
    useThemeStore.getState().setMode("system");
    const before = useThemeStore.getState().resolved;

    const stop = watchSystemTheme();

    expect(() => stop()).not.toThrow();
    expect(useThemeStore.getState().resolved).toBe(before);
  });
});
