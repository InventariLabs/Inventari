import React, {
  createContext,
  useContext,
  useEffect,
  useCallback,
  useMemo,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { logger } from "@/utils/logger";
import { modulesApi, type FocusModeResponse } from "@/lib/api/modules";
import { useAuthStore } from "../store/authStore";
import i18n from "i18next";
import { moduleRegistry } from "../lib/moduleRegistry";
import { queryKeys } from "@/hooks/queries/keys";

interface ModulesContextType {
  enabledModules: string[];
  isLoading: boolean;
  /** The organization's module list could not be read — the shell names this
   * instead of offering any work, and no default install's list is standing
   * in for an answer the backend never gave. Optional so partial context
   * mocks in tests stay valid; the provider always supplies it. */
  modulesError?: boolean;
  isModuleEnabled: (moduleName: string) => boolean;
  refreshModules: () => Promise<void>;
  /** The module the organization is focused on; null when not in focus mode or while loading. */
  focusModule: string | null;
  /** Whether the focus state is known. `focusModule: null` means "not focused" only when this is
   * "ready"; while the read is pending or after it failed the shell must neither claim a profile nor
   * offer the screens showing just one module would lock. Optional so partial context mocks stay valid (absent = ready). */
  focusStatus?: "loading" | "failed" | "ready";
  /** Read the focus state again after a failed read. */
  refreshFocus?: () => Promise<void>;
  /** Enabled modules hidden from navigation listings by focus mode; empty when not focused. */
  hiddenModules: string[];
}

const ModulesContext = createContext<ModulesContextType | undefined>(undefined);

/**
 * Fallback module list shown while the fresh list is loading or when the
 * user is signed out (mirrors a default install). The React Query cache is
 * never surfaced directly while signed out — it may hold another user's
 * modules from an earlier session in the same tab.
 */
export const FALLBACK_MODULES = [
  "core",
  "items",
  "locations",
  "categories",
  "announcements",
  "shopping_lists",
  "stats",
  "stock_takes",
  "nutrition",
  "equipment",
  "partners",
  // Frontend-only built-in modules (always active)
  "inventory",
  "spaces",
  "dashboard",
  "admin",
  "settings",
  "printing",
];

export const ModulesProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const { isAuthenticated } = useAuthStore();

  // The module list lives in the React Query cache under `queryKeys.modules.my`
  // so that existing invalidations — e.g. `invalidation.modules()` after a
  // profile switch or onboarding setup — refresh it without a page reload.
  // Previously the context fetched directly, leaving the nav stale after a
  // switch until a manual reload.
  const { data, isPending, isError, refetch } = useQuery<string[]>({
    queryKey: queryKeys.modules.my,
    queryFn: async () => {
      try {
        return await modulesApi.getMyModules();
      } catch (error) {
        logger.error("Failed to fetch enabled modules:", error);
        throw error;
      }
    },
    enabled: isAuthenticated,
    retry: false,
    refetchOnWindowFocus: false,
  });

  // A failed read is not an answer. Substituting the default install's list
  // put a module the organization had switched off back into the navigation,
  // hid the five that were actually on, and rendered the switched-off one's
  // complete route over a data panel saying "error / try again" about a 403
  // that would never clear. On failure the list is empty — core stays, the
  // shell names the outage, and nothing is offered that was never enabled.
  const enabledModules = useMemo(
    () =>
      isAuthenticated
        ? (data ?? (isError ? NO_KNOWN_MODULES : FALLBACK_MODULES))
        : FALLBACK_MODULES,
    [isAuthenticated, data, isError],
  );
  // Only block the initial authenticated load; a disabled (signed-out) query
  // never reports pending data to the shell.
  const isLoading = isAuthenticated && isPending;
  const modulesError = isAuthenticated && isError;

  // Single-module focus state (GET /modules/focus). Stays null while signed
  // out and while loading — navigation must not narrow on a guess.
  const {
    data: focusData,
    isPending: focusPending,
    isError: focusError,
    refetch: refetchFocus,
  } = useQuery<FocusModeResponse>({
    queryKey: queryKeys.modules.focus,
    queryFn: async () => {
      try {
        return await modulesApi.getFocus();
      } catch (error) {
        logger.error("Failed to fetch focus mode state:", error);
        throw error;
      }
    },
    enabled: isAuthenticated,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const focusModule = focusData?.applied
    ? (focusData.focus_module ?? null)
    : null;

  const focusStatus: "loading" | "failed" | "ready" = !isAuthenticated
    ? "ready"
    : focusError
      ? "failed"
      : focusPending
        ? "loading"
        : "ready";
  const refreshFocus = useCallback(async () => {
    await refetchFocus();
  }, [refetchFocus]);

  // In focus mode every enabled module except the focused one disappears
  // from navigation listings; its routes stay reachable by direct link.
  const hiddenModules = useMemo(
    () =>
      focusModule ? enabledModules.filter((name) => name !== focusModule) : [],
    [enabledModules, focusModule],
  );

  // Apply/revert i18n overrides whenever enabled modules change
  // or when the user switches language (new bundles are loaded, overrides must be re-applied).
  useEffect(() => {
    moduleRegistry.applyI18nOverrides(enabledModules);

    // i18n.on may be absent in test environments where i18next is a stub
    if (typeof i18n?.on !== "function") return;

    const handleLanguageChange = () => {
      moduleRegistry.applyI18nOverrides(enabledModules);
    };
    i18n.on("languageChanged", handleLanguageChange);
    return () => {
      i18n.off("languageChanged", handleLanguageChange);
    };
  }, [enabledModules]);

  // Apply/revert CSS variable theme overrides when enabled modules change.
  useEffect(() => {
    moduleRegistry.applyThemeOverrides(enabledModules);
  }, [enabledModules]);

  const isModuleEnabled = (moduleName: string) => {
    return enabledModules.includes(moduleName) || moduleName === "core";
  };

  const refreshModules = useCallback(async () => {
    await refetch();
  }, [refetch]);

  return (
    <ModulesContext.Provider
      value={{
        enabledModules,
        isLoading,
        modulesError,
        isModuleEnabled,
        refreshModules,
        focusModule,
        focusStatus,
        refreshFocus,
        hiddenModules,
      }}
    >
      {children}
    </ModulesContext.Provider>
  );
};

export const useModules = () => {
  const context = useContext(ModulesContext);
  if (context === undefined) {
    throw new Error("useModules must be used within a ModulesProvider");
  }
  return context;
};

/**
 * The enabled-module list, or an empty list when there is no provider.
 *
 * For features that *enrich* core behaviour rather than depend on it — module
 * validation rules being the first. A core form must render and save with no
 * modules context at all; throwing there would make an optional extension
 * point able to break the form it extends.
 */
export const useEnabledModulesOptional = (): string[] => {
  const context = useContext(ModulesContext);
  return context?.enabledModules ?? EMPTY_MODULES;
};

/** Stable identity so consumers' useCallback deps do not change every render. */
const EMPTY_MODULES: string[] = [];

/** What the shell knows after the module list failed to arrive: nothing. */
const NO_KNOWN_MODULES: string[] = [];
