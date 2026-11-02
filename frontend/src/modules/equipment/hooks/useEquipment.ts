import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { downloadBlob } from "@/utils/helpers";
import { useAppMutation } from "@/lib/api/mutationFactory";
import i18n from "@/i18n/config";
import { equipmentApi } from "@/modules/equipment/api/equipment";
import type { ScopeType } from "@/modules/equipment/api/equipment_campaigns";
import { assetTimelineApi } from "@/modules/equipment/api/equipment_timeline";
import { itemsApi } from "@/lib/api/items";
import type {
  AssignmentCreate,
  AssignmentCheckin,
  EquipmentModel,
  EquipmentModelCreate,
  EquipmentModelUpdate,
} from "@/modules/equipment/api/equipment";
import { sortModelsForDisplay } from "@/modules/equipment/components/assetUtils";
import type { AssetFilter } from "@/modules/equipment/api/equipment_assets";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import { queryKeys } from "@/hooks/queries/keys";
import { invalidation } from "@/lib/api/invalidation";

export function useEquipmentDashboard() {
  return useModuleQuery("equipment", {
    queryKey: queryKeys.equipment.dashboard,
    queryFn: () => equipmentApi.getDashboard(),
  });
}

export function useActiveAssignments() {
  return useModuleQuery("equipment", {
    queryKey: queryKeys.equipment.assignments.active,
    queryFn: () => equipmentApi.listActiveAssignments(),
  });
}

// Surface overdue assignments so the dashboard can flag them.
export function useOverdueAssignments(limit = 20) {
  return useModuleQuery("equipment", {
    queryKey: [...queryKeys.equipment.assignments.active, "overdue", limit],
    queryFn: () => equipmentApi.listOverdueAssignments(limit),
  });
}

export function useItemAssignmentHistory(itemId: string) {
  return useQuery({
    queryKey: queryKeys.equipment.assignments.itemHistory(itemId),
    queryFn: () => equipmentApi.getItemAssignmentHistory(itemId),
    enabled: Boolean(itemId),
  });
}

export function useItemMaintenanceLogs(itemId: string) {
  return useQuery({
    queryKey: queryKeys.equipment.maintenance.itemLogs(itemId),
    queryFn: () => equipmentApi.getItemMaintenanceLogs(itemId),
    enabled: Boolean(itemId),
  });
}

export function useAssetTimeline(itemId: string) {
  return useQuery({
    queryKey: queryKeys.equipment.timeline(itemId),
    queryFn: () => assetTimelineApi.getAssetTimeline(itemId),
    enabled: Boolean(itemId),
  });
}

export function useCheckout() {
  return useAppMutation(
    (data: AssignmentCreate) => equipmentApi.checkout(data),
    (qc) => {
      invalidation.equipment(qc);
    },
    // Without an `errorFallback` a 5xx shows the shared "The action could not
    // be completed." — true, and no help in a modal that could say which
    // action; `extractApiError` withholds the server's own `detail` there
    // because it is written for whoever reads the log. Spelled out key by
    // key rather than built from a template literal, which would hide all
    // five of them from the i18n gate.
    { errorFallback: i18n.t("equipment:assignments.checkout_failed") },
  );
}

export function useCheckin() {
  return useAppMutation(
    ({
      assignmentId,
      data,
    }: {
      assignmentId: string;
      data: AssignmentCheckin;
    }) => equipmentApi.checkin(assignmentId, data),
    (qc) => {
      invalidation.equipment(qc);
    },
    { errorFallback: i18n.t("equipment:assignments.checkin_failed") },
  );
}

export function useCreateMaintenanceLog() {
  return useAppMutation(
    equipmentApi.createMaintenanceLog,
    (qc, _data, variables) => {
      qc.invalidateQueries({
        queryKey: queryKeys.equipment.maintenance.itemLogs(variables.item_id),
      });
      invalidation.equipment(qc);
    },
    { errorFallback: i18n.t("equipment:maintenance.log_failed") },
  );
}

export function useDeleteMaintenanceLog() {
  return useAppMutation(
    (logId: string) => equipmentApi.deleteMaintenanceLog(logId),
    (qc) => {
      invalidation.equipment(qc);
    },
  );
}

/**
 * The protocol is the only paper a checkout leaves behind.
 *
 * This was the module's one raw `useMutation`, with an `onSuccess` and nothing
 * else, so a failed download produced no file and no sentence -- identical, to
 * the reader, to not having clicked at all.
 */
export function useDownloadProtocol(errorFallback?: string) {
  return useAppMutation<Blob, { assignmentId: string; templateId?: string }>(
    ({ assignmentId, templateId }) =>
      equipmentApi.downloadProtocolPdf(assignmentId, templateId),
    (_qc, blob, { assignmentId }) => {
      downloadBlob(blob, `protocol-${assignmentId.slice(0, 8)}.pdf`);
    },
    { errorFallback },
  );
}

export function useCampaigns() {
  return useModuleQuery("equipment", {
    queryKey: queryKeys.equipment.campaigns.list,
    queryFn: () => equipmentApi.listCampaigns(),
  });
}

export function useCampaignDetail(campaignId: string) {
  return useQuery({
    queryKey: queryKeys.equipment.campaigns.detail(campaignId),
    queryFn: () => equipmentApi.getCampaign(campaignId),
    enabled: Boolean(campaignId),
  });
}

export function useCreateCampaign() {
  return useAppMutation(
    (data: import("@/modules/equipment/api/equipment").CampaignCreate) =>
      equipmentApi.createCampaign(data),
    (qc) => {
      invalidation.equipment(qc);
    },
  );
}

export function useLaunchCampaign() {
  return useAppMutation(
    (campaignId: string) => equipmentApi.launchCampaign(campaignId),
    (qc, _data, campaignId) => {
      invalidation.equipment(qc);
      qc.invalidateQueries({
        queryKey: queryKeys.equipment.campaigns.detail(campaignId),
      });
    },
  );
}

/**
 * What a campaign's scope covers, before anything is sent.
 *
 * Both places that used to ask the reader to commit without a number read
 * this: the creation screen's scope picker and the launch confirmation.
 */
export function useScopePreview(scopeType: ScopeType, scopeFilterId?: string) {
  // A narrowed scope without a filter has nothing to count, and asking would
  // report the whole organization as the answer.
  return useModuleQuery("equipment", {
    queryKey: queryKeys.equipment.campaigns.scopePreview(
      scopeType,
      scopeFilterId ?? "",
    ),
    queryFn: () => equipmentApi.scopePreview(scopeType, scopeFilterId),
    extraEnabled: scopeType === "ALL" || Boolean(scopeFilterId),
  });
}

export function useSendReminders() {
  return useAppMutation(
    (campaignId: string) => equipmentApi.sendReminders(campaignId),
    (qc, _data, campaignId) => {
      qc.invalidateQueries({
        queryKey: queryKeys.equipment.campaigns.detail(campaignId),
      });
    },
  );
}

export function useCompleteCampaign() {
  return useAppMutation(
    (campaignId: string) => equipmentApi.completeCampaign(campaignId),
    (qc) => {
      invalidation.equipment(qc);
    },
  );
}

export function useCancelCampaign() {
  return useAppMutation(
    (campaignId: string) => equipmentApi.cancelCampaign(campaignId),
    (qc, _data, campaignId) => {
      invalidation.equipment(qc);
      qc.invalidateQueries({
        queryKey: queryKeys.equipment.campaigns.detail(campaignId),
      });
    },
  );
}

export function useDeleteCampaign() {
  return useAppMutation(
    (campaignId: string) => equipmentApi.deleteCampaign(campaignId),
    (qc) => {
      invalidation.equipment(qc);
    },
  );
}

export function useEquipmentModels() {
  const { i18n } = useTranslation();
  return useModuleQuery("equipment", {
    queryKey: queryKeys.equipment.models,
    queryFn: () => equipmentApi.listModels(),
    // The payload is language-independent; only the order a reader scans
    // it in follows the UI language, so the sort is a view over the cached
    // list (select), not a reason to refetch it.
    select: (models: EquipmentModel[]) =>
      sortModelsForDisplay(models, i18n.language),
  });
}

export function useCreateEquipmentModel() {
  return useAppMutation(
    (data: EquipmentModelCreate) => equipmentApi.createModel(data),
    (qc) => {
      invalidation.equipment(qc);
    },
  );
}

export function useUpdateEquipmentModel() {
  return useAppMutation(
    ({ modelId, data }: { modelId: string; data: EquipmentModelUpdate }) =>
      equipmentApi.updateModel(modelId, data),
    (qc) => {
      invalidation.equipment(qc);
    },
  );
}

export function useDeleteEquipmentModel() {
  return useAppMutation(
    (modelId: string) => equipmentApi.deleteModel(modelId),
    (qc) => {
      invalidation.equipment(qc);
    },
  );
}

export function useCloneEquipmentModel() {
  return useAppMutation(
    (modelId: string) => equipmentApi.cloneModel(modelId),
    (qc) => {
      invalidation.equipment(qc);
    },
  );
}

export function useRetireEquipment() {
  return useAppMutation(
    (itemId: string) => equipmentApi.retireItem(itemId),
    (qc) => {
      invalidation.equipment(qc);
    },
  );
}

export function useArchiveEquipment() {
  return useAppMutation(
    (itemId: string) => equipmentApi.archiveItem(itemId),
    (qc) => {
      invalidation.equipment(qc);
    },
  );
}

export function usePurgeEquipment() {
  return useAppMutation(
    ({ itemId, reason }: { itemId: string; reason?: string }) =>
      itemsApi.purge(itemId, reason),
    (qc) => {
      invalidation.equipment(qc);
    },
  );
}

export function useRestoreEquipment() {
  return useAppMutation(
    (itemId: string) => itemsApi.restore(itemId),
    (qc) => {
      invalidation.equipment(qc);
    },
  );
}

export function useBulkRetireEquipment() {
  return useAppMutation(
    (itemIds: string[]) => equipmentApi.bulkRetire(itemIds),
    (qc) => {
      invalidation.equipment(qc);
    },
  );
}

export function useBulkArchiveEquipment() {
  return useAppMutation(
    (itemIds: string[]) => equipmentApi.bulkArchive(itemIds),
    (qc) => {
      invalidation.equipment(qc);
    },
  );
}

export function useRetireMatchingAssets() {
  return useAppMutation(
    (scope: AssetFilter) => equipmentApi.retireMatching(scope),
    (qc) => {
      invalidation.equipment(qc);
    },
  );
}

export function useArchiveMatchingAssets() {
  return useAppMutation(
    (scope: AssetFilter) => equipmentApi.archiveMatching(scope),
    (qc) => {
      invalidation.equipment(qc);
    },
  );
}

export function useBulkReturnEquipment() {
  return useAppMutation(
    (payload: {
      item_ids: string[];
      checkin_condition: string;
      checkin_notes?: string;
      return_location_id?: string;
    }) => equipmentApi.bulkReturn(payload),
    (qc) => {
      invalidation.equipment(qc);
    },
    { errorFallback: i18n.t("equipment:list.bulk_return_failed") },
  );
}

export function useBulkPurgeEquipment() {
  return useAppMutation(
    (itemIds: string[]) => equipmentApi.bulkPurge(itemIds),
    (qc) => {
      invalidation.equipment(qc);
    },
  );
}

export function useBulkEditAssets() {
  return useAppMutation(
    equipmentApi.bulkEdit,
    (qc) => {
      invalidation.equipment(qc);
    },
    { errorFallback: i18n.t("equipment:list.bulk_edit_failed") },
  );
}

export function useEquipmentImportExecute() {
  return useAppMutation(
    ({
      file,
      mapping,
      defaultLocationId,
      defaultCategoryId,
    }: {
      file: File;
      mapping: Record<string, string>;
      defaultLocationId?: string;
      defaultCategoryId?: string;
    }) =>
      equipmentApi.executeImport(
        file,
        mapping,
        defaultLocationId,
        defaultCategoryId,
      ),
    (qc) => {
      invalidation.equipment(qc);
    },
  );
}
