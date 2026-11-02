import {
  useQuery,
  type UseQueryOptions,
  type UseQueryResult,
} from "@tanstack/react-query";
import { useModules } from "@/contexts/ModulesContext";

/**
 * Drop-in replacement for `useQuery` that automatically disables the
 * query when the given module is not enabled.
 *
 * Eliminates the repeated pattern:
 * ```ts
 * const { isModuleEnabled } = useModules();
 * return useQuery({ ..., enabled: isModuleEnabled("xxx") });
 * ```
 *
 * For queries that need an extra condition beyond module enablement
 * (e.g. `enabled: isModuleEnabled("recipes") && !!id`), pass the
 * additional condition as `extraEnabled`.
 *
 * @example
 * // Simple
 * return useModuleQuery("partners", {
 *   queryKey: [...queryKeys.partners.all, params],
 *   queryFn: () => partnersApi.list(params),
 * });
 *
 * @example
 * // With extra condition
 * return useModuleQuery("recipes", {
 *   queryKey: queryKeys.recipes.detail(id!),
 *   queryFn: () => recipesApi.getById(id!),
 *   extraEnabled: !!id,
 * });
 */
export function useModuleQuery<
  TData = unknown,
  TError = Error,
  TQueryKey extends readonly unknown[] = readonly unknown[],
>(
  moduleName: string,
  options: Omit<UseQueryOptions<TData, TError, TData, TQueryKey>, "enabled"> & {
    /** Additional condition ANDed with the module-enabled check. */
    extraEnabled?: boolean;
  },
): UseQueryResult<TData, TError> {
  const { isModuleEnabled, isLoading } = useModules();
  const { extraEnabled, ...queryOptions } = options;

  return useQuery<TData, TError, TData, TQueryKey>({
    ...queryOptions,
    // A module list still loading is the default install's guess, not this
    // organization's answer. Firing on it asks endpoints of modules the org
    // may not have — a 403 the reader never caused and cannot fix.
    enabled:
      !isLoading && isModuleEnabled(moduleName) && (extraEnabled ?? true),
  });
}
