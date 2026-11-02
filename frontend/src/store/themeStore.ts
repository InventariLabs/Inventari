import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * What the user chose. "system" defers to `prefers-color-scheme`, which is the
 * default: a visitor whose desktop is dark used to be handed a light interface
 * on the first visit, with no way to say "follow my system" afterwards.
 */
export type ThemeMode = "light" | "dark" | "system";

/** What is actually on screen once "system" has been resolved. */
export type ResolvedTheme = "light" | "dark";

const DARK_QUERY = "(prefers-color-scheme: dark)";

function darkMediaQuery(): MediaQueryList | null {
  if (
    typeof window === "undefined" ||
    typeof window.matchMedia !== "function"
  ) {
    return null;
  }
  return window.matchMedia(DARK_QUERY);
}

function resolveMode(mode: ThemeMode): ResolvedTheme {
  if (mode !== "system") return mode;
  return darkMediaQuery()?.matches ? "dark" : "light";
}

function applyThemeToDOM(resolved: ResolvedTheme): void {
  if (resolved === "dark") {
    document.documentElement.classList.add("dark");
  } else {
    document.documentElement.classList.remove("dark");
  }
}

interface ThemeState {
  mode: ThemeMode;
  /** Derived from `mode`; never persisted, because the system may have changed. */
  resolved: ResolvedTheme;
  setMode: (mode: ThemeMode) => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      mode: "system" as ThemeMode,
      resolved: "light" as ResolvedTheme,
      setMode: (mode: ThemeMode) => {
        const resolved = resolveMode(mode);
        applyThemeToDOM(resolved);
        set({ mode, resolved });
      },
    }),
    {
      name: "inventari-theme",
      partialize: (state) => ({ mode: state.mode }),
      // With a synchronous storage zustand rehydrates while create() is still
      // running, so the old onRehydrateStorage callback's
      // `useThemeStore.setState({ resolved })` hit the temporal dead zone and
      // threw a ReferenceError persist silently swallowed — html got .dark but
      // the store kept resolved: "light" and the profile palette never
      // remapped. merge() receives the current state as an argument,
      // so the persisted mode can be resolved and painted without ever
      // referencing the store itself.
      merge: (persisted, current) => {
        const stored = (persisted ?? {}) as Partial<Pick<ThemeState, "mode">>;
        const mode = stored.mode ?? current.mode;
        const resolved = resolveMode(mode);
        applyThemeToDOM(resolved);
        return { ...current, mode, resolved };
      },
      onRehydrateStorage: () => (_state, error) => {
        // persist hands a failed hydration to this callback's `error`
        // argument — the old code read only `state`, so a broken storage or a
        // thrown rehydration vanished without a trace. Say it out loud.
        if (error) {
          console.error("[themeStore] theme rehydration failed:", error);
        }
      },
    },
  ),
);

/**
 * Keeps the interface in step with the system while the user is on "system".
 * Returns an unsubscribe function. Call once at start-up.
 */
export function watchSystemTheme(): () => void {
  const mql = darkMediaQuery();
  if (!mql) return () => {};

  const onChange = (event: MediaQueryListEvent) => {
    if (useThemeStore.getState().mode !== "system") return;
    const resolved: ResolvedTheme = event.matches ? "dark" : "light";
    applyThemeToDOM(resolved);
    useThemeStore.setState({ resolved });
  };

  mql.addEventListener("change", onChange);
  return () => mql.removeEventListener("change", onChange);
}
