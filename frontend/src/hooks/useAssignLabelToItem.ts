import { useAppMutation } from "@/lib/api/mutationFactory";
import { labelsApi } from "@/lib/api/labels";
import { invalidation } from "@/lib/api/invalidation";

/**
 * Binds a free pool label to a product that already exists. The product's
 * record carries the label code, so its caches clear with the pool's.
 */
export function useAssignLabelToItem() {
  return useAppMutation(
    (vars: { shortCode: string; itemId: string }) =>
      labelsApi.assignToExistingItem(vars.shortCode, vars.itemId),
    (qc) => {
      invalidation.labels(qc);
      invalidation.items(qc);
    },
  );
}
