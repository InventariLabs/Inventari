import { useQuery, keepPreviousData } from "@tanstack/react-query";
import i18n from "@/i18n/config";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { labelsApi } from "@/module-sdk";
import { invalidation } from "@/lib/api/invalidation";
import { queryKeys } from "@/hooks/queries/keys";
import type { LabelPoolListResponse } from "@/types";

export function useLabels(
  unassignedOnly = false,
  labelType?: string,
  pagination?: { status?: string; offset?: number; limit?: number },
) {
  return useQuery<LabelPoolListResponse>({
    queryKey: [...queryKeys.labels.all, unassignedOnly, labelType, pagination],
    queryFn: () =>
      labelsApi.getPool({
        unassigned_only: unassignedOnly,
        label_type: labelType,
        ...pagination,
      }),
    placeholderData: pagination ? keepPreviousData : undefined,
  });
}

export function useGenerateLabels() {
  return useAppMutation(
    (data: Parameters<typeof labelsApi.generatePool>[0]) => {
      const sanitizedData = {
        ...data,
        description: data.description?.trim() || null,
        target_location_id: data.target_location_id || null,
        // "" is the product purpose, which the pool records as no tag at all.
        context_tag: data.context_tag || null,
      };
      return labelsApi.generatePool(
        sanitizedData as Parameters<typeof labelsApi.generatePool>[0],
      );
    },
    (qc) => {
      invalidation.labels(qc);
    },
  );
}

export function useDeleteLabel() {
  return useAppMutation(
    (id: string) => labelsApi.delete(id),
    (qc) => {
      invalidation.labels(qc);
    },
  );
}

export function useBulkDeleteLabels() {
  return useAppMutation(
    async (ids: string[]) => {
      for (const id of ids) {
        await labelsApi.delete(id);
      }
    },
    (qc) => {
      invalidation.labels(qc);
    },
  );
}

export function useUnassignLabel() {
  return useAppMutation(
    (shortCode: string) => labelsApi.unassign(shortCode),
    (qc) => {
      invalidation.labels(qc);
      // The product carries the code too (`label_code`): a page that still
      // shows the freed label would offer to free it again.
      invalidation.items(qc);
    },
    // Both places that free a label leave the failure to the default toast;
    // without a fallback it read "The action could not be completed."
    { errorFallback: i18n.t("labels:actions.freeLabelFailed") },
  );
}

export function useExportLabelPng() {
  return useAppMutation(
    (params: {
      count: number;
      labelIds?: string[];
      shortCodes?: string[];
      width: number;
      height: number;
      baseUrl?: string;
      description?: string;
      qrOnly?: boolean;
      media?: string;
      showCode?: boolean;
    }) => labelsApi.exportPng(params),
    (qc) => {
      invalidation.labels(qc);
    },
  );
}
