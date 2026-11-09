import { AlertTriangle, ClipboardList } from "lucide-react";
import { api } from "@/module-sdk";
import { queryKeys } from "@/hooks/queries/keys";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import { useHasPermission } from "@/hooks/useHasPermission";
import type { ActionItem } from "@/lib/moduleRegistry";

/**
 * useInventoryActionItems — returns launcher action items for inventory.
 * Shows in-progress stock takes so users can quick-navigate to complete them.
 *
 * The rows come from the stock-takes endpoint, so the stock-takes module
 * owns the question: for an organization that has it switched off the tile
 * has nothing to say, and asking anyway bought a 403 on every launcher load.
 * The endpoint is read with this module's own client: stock takes are
 * optional here, and an import of their files cannot be. Only the total is
 * read. A role without the stock takes' read is not asked either: the
 * endpoint refuses it, and the row then said the count could not be
 * checked — a failure that was a rule.
 */
export function useInventoryActionItems(): ActionItem[] {
  const mayRead = useHasPermission("stock_takes:read");
  const { data, isError } = useModuleQuery("stock_takes", {
    queryKey: queryKeys.stockTakes.launcherActions,
    queryFn: async () =>
      (
        await api.get<{ total: number }>("/stock-takes", {
          params: { status_filter: "in_progress", limit: 5 },
        })
      ).data,
    staleTime: 2 * 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
    retry: 1,
    extraEnabled: mayRead,
  });

  // A failed read is not "nothing in progress": with no card at all the
  // launcher would say exactly that. Say the count could not be taken,
  // pointing at the list that shows the failure in full.
  if (!mayRead) return [];
  if (isError) {
    return [
      {
        id: "inventory-stock-takes-unavailable",
        labelKey: "inventory:actions.stockTakesUnavailable",
        icon: AlertTriangle,
        severity: "error",
        linkTo: "/inventory/stock-takes",
      },
    ];
  }
  const count = data?.total ?? 0;
  if (count === 0) return [];

  return [
    {
      id: "inventory-stock-takes-in-progress",
      labelKey: "inventory:actions.stockTakesInProgress",
      icon: ClipboardList,
      severity: "warning",
      linkTo: "/inventory/stock-takes?status=in_progress",
      count,
    },
  ];
}
