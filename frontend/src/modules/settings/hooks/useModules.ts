import { useQuery, useMutation } from "@tanstack/react-query";
import { useAppMutation } from "@/lib/api/mutationFactory";
import {
  modulesApi,
  type FocusModeResponse,
  type ModuleEnablePreview,
} from "@/lib/api/modules";
import { invalidation } from "@/lib/api/invalidation";
import { queryKeys } from "@/hooks/queries/keys";
import type { ModuleInfo } from "@/types";

export function useMyModules() {
  return useQuery<string[]>({
    queryKey: queryKeys.modules.my,
    queryFn: () => modulesApi.getMyModules(),
  });
}

export function useAvailableModules() {
  return useQuery<ModuleInfo[]>({
    queryKey: queryKeys.modules.available,
    queryFn: () => modulesApi.getAvailable(),
  });
}

/**
 * Single-module focus state of the organization.
 *
 * `focusModule` names the module the organization is focused on, and is
 * `null` while the state is loading, while not in focus mode, or when the
 * response names no module — callers only need to know which module, if
 * any, owns the screen right now.
 */
export function useFocusModule() {
  const query = useQuery<FocusModeResponse>({
    queryKey: queryKeys.modules.focus,
    queryFn: () => modulesApi.getFocus(),
  });
  const focusModule = query.data?.applied
    ? (query.data.focus_module ?? null)
    : null;
  return { ...query, focusModule };
}

export function useToggleModule() {
  return useAppMutation(
    ({ moduleName, enabled }: { moduleName: string; enabled: boolean }) =>
      modulesApi.toggleModule(moduleName, enabled),
    (qc) => {
      invalidation.modules(qc);
    },
  );
}

/**
 * Ask a module what switching it on would put into motion.
 *
 * Read-only, so a plain `useMutation` like the focus preview: the caller
 * decides what to do with the number, and nothing needs invalidating.
 */
export function useModuleEnablePreview() {
  return useMutation<ModuleEnablePreview, Error, string>({
    mutationFn: (moduleName: string) => modulesApi.enablePreview(moduleName),
  });
}

/**
 * Preview entering single-module focus without committing it.
 *
 * A plain `useMutation` (mirroring `useProfileSwitchPreview`): the request is
 * read-only, so no caches need invalidation — the caller decides what to do
 * with the returned diff.
 */
export function useFocusModePreview() {
  return useMutation<FocusModeResponse, Error, string>({
    mutationFn: (moduleName: string) => modulesApi.previewFocus(moduleName),
  });
}

/**
 * Enter single-module focus on a module. Mirrors the profile-switch apply
 * hook: the enabled set changes, so the module list, the focus state and the
 * organization all refresh, and stats counts may shift with them.
 */
export function useFocusModeApply() {
  return useAppMutation<FocusModeResponse, string>(
    (moduleName: string) => modulesApi.applyFocus(moduleName),
    (qc) => {
      invalidation.organization(qc);
      invalidation.modules(qc);
      invalidation.stats(qc);
    },
    {
      errorFallback: "Failed to show just one module",
    },
  );
}

/** Exit single-module focus; same invalidations as entering it. */
export function useFocusModeExit() {
  return useAppMutation<FocusModeResponse, void>(
    () => modulesApi.exitFocus(),
    (qc) => {
      invalidation.organization(qc);
      invalidation.modules(qc);
      invalidation.stats(qc);
    },
    {
      errorFallback: "Failed to show all modules again",
    },
  );
}
