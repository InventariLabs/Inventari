import { useAppMutation } from "@/lib/api/mutationFactory";
import { itemsApi } from "@/lib/api/items";
import { invalidation } from "@/lib/api/invalidation";
import { queryKeys } from "@/hooks/queries/keys";

export function useDeleteItemFromStorage(storageId: string) {
  return useAppMutation(
    ({
      itemId,
      reason,
      notes,
    }: {
      itemId: string;
      reason?: string;
      notes?: string;
    }) => itemsApi.delete(itemId, reason, notes),
    (qc) => {
      invalidation.items(qc, storageId);
      invalidation.storages(qc, storageId);
      qc.invalidateQueries({ queryKey: queryKeys.items.archived });
    },
  );
}

export function useConsumeItemFromStorage(storageId: string) {
  return useAppMutation(
    ({
      itemId,
      quantity = 1,
      reason = "USED",
    }: {
      itemId: string;
      quantity?: number;
      reason?: string;
    }) => itemsApi.consume(itemId, quantity, reason),
    (qc) => {
      invalidation.items(qc, storageId);
      invalidation.storages(qc, storageId);
    },
  );
}
