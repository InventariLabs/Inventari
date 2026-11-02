import { useAppMutation } from "@/lib/api/mutationFactory";
import { itemsApi, type LabelMatchMode } from "@/lib/api/items";
import { productTemplatesApi } from "@/lib/api/productTemplates";
import type { ItemCreate, ItemUpdate, ItemBulkUpdate } from "@/types";
import { invalidation } from "@/lib/api/invalidation";
import { queryKeys } from "@/hooks/queries/keys";

export function useCreateItem() {
  return useAppMutation(
    (data: ItemCreate) => itemsApi.create(data),
    (qc) => {
      invalidation.items(qc);
    },
  );
}

export function useUpdateItem() {
  return useAppMutation(
    ({ id, data }: { id: string; data: Record<string, unknown> }) =>
      itemsApi.update(id, data as ItemUpdate),
    (qc, _result, { id }) => {
      qc.invalidateQueries({ queryKey: queryKeys.items.detail(id) });
      invalidation.items(qc);
    },
  );
}

export function useDeleteItem() {
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
      invalidation.items(qc);
      qc.invalidateQueries({ queryKey: queryKeys.items.archived });
    },
  );
}

export function useConsumeItem() {
  return useAppMutation(
    ({
      itemId,
      quantity = 1,
      reason = "USED",
      notes,
    }: {
      itemId: string;
      quantity?: number;
      reason?: string;
      notes?: string;
    }) => itemsApi.consume(itemId, quantity, reason, notes),
    (qc) => {
      invalidation.items(qc);
    },
  );
}

export function useDiscardItem() {
  return useAppMutation(
    ({
      itemId,
      quantity = 1,
      reason = "DISPOSED",
      notes,
    }: {
      itemId: string;
      quantity?: number;
      reason?: string;
      notes?: string;
    }) => itemsApi.discard(itemId, quantity, reason, notes),
    (qc) => {
      invalidation.items(qc);
    },
  );
}

export function useMoveItem() {
  return useAppMutation(
    ({
      itemId,
      storageLocationId,
    }: {
      itemId: string;
      storageLocationId: string;
    }) => itemsApi.move(itemId, storageLocationId),
    (qc, _result, { itemId }) => {
      // The item screen reads the detail query under the ["items"] root,
      // not the lists —
      // a move that only invalidated lists left a consumed-to-zero position
      // reporting "Consumed (Virtual)" with the old instruction paragraph
      // after a successful move, until a manual reload.
      qc.invalidateQueries({ queryKey: queryKeys.items.detail(itemId) });
      invalidation.items(qc);
      invalidation.storages(qc);
    },
  );
}

export function useUpdateItemQuantity() {
  return useAppMutation(
    ({ itemId, quantity }: { itemId: string; quantity: number }) =>
      itemsApi.updateQuantity(itemId, quantity),
    (qc, _result, { itemId }) => {
      qc.invalidateQueries({ queryKey: queryKeys.items.detail(itemId) });
      invalidation.items(qc);
    },
  );
}

export function useBulkUpdateItems() {
  return useAppMutation(
    (data: ItemBulkUpdate) => itemsApi.bulkUpdate(data),
    (qc) => {
      invalidation.items(qc);
    },
  );
}

export function useRestoreItem() {
  return useAppMutation(
    (itemId: string) => itemsApi.restore(itemId),
    (qc) => {
      invalidation.items(qc);
      qc.invalidateQueries({ queryKey: queryKeys.items.archived });
    },
  );
}

export function usePurgeItem() {
  return useAppMutation(
    ({ itemId, reason }: { itemId: string; reason?: string }) =>
      itemsApi.purge(itemId, reason),
    (qc) => {
      invalidation.items(qc);
      qc.invalidateQueries({ queryKey: queryKeys.items.archived });
    },
  );
}

export function useImportItems() {
  return useAppMutation(
    ({
      file,
      mapping,
      createLocations = true,
      createCategories = true,
      onLabelMatch = "add",
    }: {
      file: File;
      mapping: unknown;
      createLocations?: boolean;
      createCategories?: boolean;
      onLabelMatch?: LabelMatchMode;
    }) =>
      itemsApi.importItems(
        file,
        mapping,
        createLocations,
        createCategories,
        onLabelMatch,
      ),
    (qc, result) => {
      invalidation.items(qc);
      // A file that names locations or categories the organization does not
      // have founds them on the way, and the product list resolves its
      // location column names from the storages cache — refreshing only the
      // products left a newly founded location reading "Unknown" on the very
      // row that named it until a reload. The response says which of the two
      // this import founded, and only those lists are refetched.
      if (result.created_locations.length > 0) invalidation.storages(qc);
      if (result.created_categories.length > 0) invalidation.categories(qc);
    },
  );
}

/** An internal code for the product form's barcode field; nothing to refresh,
 *  since nothing is saved until the form is. */
export function useGenerateProductCode() {
  return useAppMutation(
    () => productTemplatesApi.generateBarcode(),
    () => {},
  );
}
