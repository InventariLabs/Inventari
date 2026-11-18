import { useAppMutation } from "@/lib/api/mutationFactory";
import { storagesApi, type StorageLocationUpdate } from "@/lib/api/storages";
import type { StorageLocation } from "@/types";
import { invalidation } from "@/lib/api/invalidation";

export function useCreateStorage() {
  return useAppMutation(
    (data: Partial<StorageLocation>) => storagesApi.create(data),
    (qc) => {
      invalidation.storages(qc);
    },
  );
}

export function useUpdateStorage(errorFallback?: string) {
  return useAppMutation(
    ({ id, data }: { id: string; data: StorageLocationUpdate }) =>
      storagesApi.update(id, data),
    (qc, _result, { id }) => {
      invalidation.storages(qc, id);
    },
    { errorFallback },
  );
}

export function useDeleteStorage(errorFallback?: string) {
  return useAppMutation(
    (storageId: string) => storagesApi.delete(storageId),
    (qc, _data, storageId) => {
      invalidation.storageDeleted(qc, storageId);
    },
    { errorFallback },
  );
}

/** Archiving a place that holds nothing: the way out when a delete is refused
 * because the place is part of an asset's history. */
export function useArchiveStorage(errorFallback?: string) {
  return useAppMutation(
    (storageId: string) => storagesApi.archive(storageId),
    (qc, _data, storageId) => {
      invalidation.storages(qc, storageId);
    },
    { errorFallback },
  );
}

export function useCreateStorageHierarchy(errorFallback?: string) {
  return useAppMutation(
    (data: Parameters<typeof storagesApi.createHierarchy>[0]) =>
      storagesApi.createHierarchy(data),
    (qc) => {
      invalidation.storages(qc);
    },
    { errorFallback },
  );
}
