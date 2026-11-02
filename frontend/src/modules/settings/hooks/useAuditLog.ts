import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { auditLogApi, type AuditLogFilters } from "@/lib/api/auditLog";
import { queryKeys } from "@/hooks/queries/keys";

export function useAuditLog(filters: AuditLogFilters = {}) {
  return useQuery({
    queryKey: queryKeys.auditLog.list(filters),
    queryFn: () => auditLogApi.list(filters),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}

/** The target types the log actually holds — the only honest filter list. */
export function useAuditTargetTypes() {
  return useQuery({
    queryKey: queryKeys.auditLog.targetTypes,
    queryFn: auditLogApi.targetTypes,
    staleTime: 60_000,
  });
}
