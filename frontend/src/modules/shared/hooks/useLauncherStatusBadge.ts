import { useQuery, type QueryKey } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useModules } from "@/contexts/ModulesContext";

interface UseLauncherStatusBadgeArgs<TData> {
  queryKey: QueryKey;
  queryFn: () => Promise<TData>;
  labelKey: string;
  /** Namespace from which labelKey is resolved (e.g. "inventory"). */
  labelNs?: string;
  staleTime: number;
  refetchInterval: number;
  extractCount: (data: TData) => number;
}

/**
 * Generic launcher-tile status badge. Returns {count,label} when the
 * fetched count is non-zero, {failed} when the read failed, otherwise null.
 * Polling cadence is caller-controlled via staleTime/refetchInterval.
 */
export function useLauncherStatusBadge<TData>({
  queryKey,
  queryFn,
  labelKey,
  labelNs,
  staleTime,
  refetchInterval,
  extractCount,
}: UseLauncherStatusBadgeArgs<TData>): {
  count: number;
  label: string;
  /** The count could not be read; the tile says so instead of showing nothing. */
  failed?: boolean;
} | null {
  const { t } = useTranslation(labelNs);
  // The launcher renders tiles from the module list; while that list is still
  // loading it holds the default install's guess, and a badge query fired on
  // the guess asks an endpoint the organization may not have (the warranty
  // alerts the onboarding console showed as 403).
  const { isLoading } = useModules();
  const { data, isError } = useQuery({
    queryKey,
    queryFn,
    staleTime,
    refetchInterval,
    retry: 1,
    enabled: !isLoading,
  });
  // A failed refresh outranks the last good answer: a cached zero must not
  // keep reading as "nothing to do" once the source stopped answering.
  if (isError) return { count: 0, label: "", failed: true };
  if (!data) return null;
  const count = extractCount(data);
  // CRITICAL: never render a "0" badge.
  if (count <= 0) return null;
  return { count, label: t(labelKey, { count }) };
}
