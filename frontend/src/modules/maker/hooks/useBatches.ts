import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/hooks/queries/keys";
import { invalidation } from "@/lib/api/invalidation";
import {
  batchesApi,
  type IngredientBatchQuery,
} from "@/modules/maker/api/batches";

/** Which batches each ingredient of a run would come from; idle until named. */
export function useIngredientBatches(query: IngredientBatchQuery | null) {
  return useQuery({
    queryKey: queryKeys.maker.ingredientBatches(query),
    queryFn: () => batchesApi.ingredientBatches(query as IngredientBatchQuery),
    enabled: query !== null,
    placeholderData: (prev) => prev,
  });
}

export function useShelfLife(templateId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.maker.shelfLife(templateId ?? ""),
    queryFn: () => batchesApi.shelfLife(templateId as string),
    enabled: !!templateId,
  });
}

export function useSetShelfLife(templateId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (days: number | null) =>
      batchesApi.setShelfLife(templateId, days),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.maker.shelfLife(templateId), saved);
    },
  });
}

/** Hold the run's output batch, or release it: the batch's state changed. */
export function useOutputBatchStatus(orderId: string) {
  const queryClient = useQueryClient();
  const refresh = () => {
    invalidation.maker(queryClient, orderId);
    queryClient.invalidateQueries({ queryKey: queryKeys.stockLots.all });
    queryClient.invalidateQueries({ queryKey: queryKeys.stockQuants.all });
  };
  const hold = useMutation({
    mutationFn: (reason: string) => batchesApi.hold(orderId, reason),
    onSuccess: refresh,
  });
  const release = useMutation({
    mutationFn: () => batchesApi.release(orderId),
    onSuccess: refresh,
  });
  return { hold, release };
}

export function useBatchRecord(orderId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.maker.batchRecord(orderId ?? ""),
    queryFn: () => batchesApi.record(orderId as string),
    enabled: !!orderId,
  });
}

export function useRunAttachments(orderId: string) {
  const queryClient = useQueryClient();
  const key = queryKeys.maker.runAttachments(orderId);
  const list = useQuery({
    queryKey: key,
    queryFn: () => batchesApi.attachments(orderId),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: key });
  const upload = useMutation({
    mutationFn: (file: File) => batchesApi.uploadAttachment(orderId, file),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (attachmentId: string) =>
      batchesApi.deleteAttachment(orderId, attachmentId),
    onSuccess: refresh,
  });
  return { list, upload, remove };
}
