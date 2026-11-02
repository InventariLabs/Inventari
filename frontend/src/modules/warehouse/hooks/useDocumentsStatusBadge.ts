import { queryKeys } from "@/hooks/queries/keys";
import { useLauncherStatusBadge } from "@/modules/shared/hooks/useLauncherStatusBadge";
import { fetchDocumentsTodoCount } from "@/modules/warehouse/hooks/useDocumentsTodo";

/** Launcher tile badge: confirmed documents waiting for the floor today. */
export function useDocumentsStatusBadge() {
  return useLauncherStatusBadge({
    queryKey: [...queryKeys.documents.all, "todo-count"],
    queryFn: fetchDocumentsTodoCount,
    labelKey: "statusBadge.todo",
    labelNs: "warehouse",
    staleTime: 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
    extractCount: (count) => count,
  });
}
