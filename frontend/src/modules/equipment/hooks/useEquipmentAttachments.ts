import { useQuery } from "@tanstack/react-query";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { equipmentApi } from "@/modules/equipment/api/equipment";
import { queryKeys } from "@/hooks/queries/keys";
import type { EquipmentAttachment } from "@/modules/equipment/api/equipment";

export function useEquipmentAttachments(itemId: string) {
  return useQuery<EquipmentAttachment[]>({
    queryKey: [...queryKeys.equipment.assets.detail(itemId), "attachments"],
    queryFn: () => equipmentApi.listAttachments(itemId),
    enabled: Boolean(itemId),
  });
}

export function useUploadAttachment(itemId: string) {
  return useAppMutation(
    ({ file, fileType }: { file: File; fileType: string }) =>
      equipmentApi.uploadAttachment(itemId, file, fileType),
    (qc) => {
      qc.invalidateQueries({
        queryKey: [...queryKeys.equipment.assets.detail(itemId), "attachments"],
      });
    },
  );
}

export function useDeleteAttachment(itemId: string) {
  return useAppMutation(
    (attachmentId: string) =>
      equipmentApi.deleteAttachment(itemId, attachmentId),
    (qc) => {
      qc.invalidateQueries({
        queryKey: [...queryKeys.equipment.assets.detail(itemId), "attachments"],
      });
    },
  );
}
