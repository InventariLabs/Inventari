import { useQuery } from "@tanstack/react-query";
import { itemsApi } from "@/lib/api/items";
import type { AttentionCounts } from "@/types";
import { queryKeys } from "@/hooks/queries/keys";

/**
 * What needs attention, from the one place that answers it.
 *
 * `GET /items/attention-counts` counts expired and expiring-soon records
 * plus short products — uncapped, and product-level for low stock, which
 * is the rule the purchasing engine reads. The inventory dashboard's
 * heading and the statistics health card both read this hook, so one
 * organization has one number rather than two independent computations
 * of the same concept.
 *
 * `excludeModuleContexts` is the organization's "show module data"
 * setting, passed the way the item list passes it: both screens narrow to
 * the same rows, so a heading never counts a record the list would hide.
 */
export function useAttentionCounts(excludeModuleContexts: boolean) {
  return useQuery<AttentionCounts>({
    queryKey: [
      ...queryKeys.items.all,
      "attention-counts",
      excludeModuleContexts,
    ],
    queryFn: () =>
      itemsApi.getAttentionCounts({
        exclude_module_contexts: excludeModuleContexts,
      }),
  });
}

/**
 * The heading's number: the rows the "needs attention" list opens with. The
 * shares do not sum to it: `low_stock` counts products and the list shows
 * their records, so a heading summed from them said 14 over a list of 17.
 */
export function attentionCount(counts: AttentionCounts | undefined): number {
  return counts?.records ?? 0;
}
