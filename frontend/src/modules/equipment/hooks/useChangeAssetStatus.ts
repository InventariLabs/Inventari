import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";
import type { EquipmentStatus } from "@/modules/equipment/components/AssetStatusBadge";
import { useBulkEditAssets } from "@/modules/equipment/hooks/useEquipment";

/**
 * Moves one asset to another status and tells the reader what happened.
 *
 * The asset page's status menu and the repair entry that takes an asset out
 * of circulation both change a status; the answer they owe is the same —
 * the backend's own reason when it refuses, a confirmation when it does not.
 */
export function useChangeAssetStatus(id: string | undefined) {
  const { t } = useTranslation("equipment");
  const { mutate: bulkEditAssets, isPending } = useBulkEditAssets();

  const changeStatus = useCallback(
    (newStatus: EquipmentStatus) => {
      if (!id) return;
      bulkEditAssets(
        {
          item_ids: [id],
          action: "change_status",
          data: { status: newStatus },
        },
        {
          onSuccess: (result) => {
            if (result.errors.length > 0) {
              // The backend says why — "no active assignment", "still checked
              // out" — and that is the only part the reader can act on.
              toast.error(
                result.errors[0]?.error ??
                  t("detail.status_change_failed", "Status change failed"),
              );
            } else {
              toast.success(
                t("detail.status_changed", {
                  status: t(`status.${newStatus.toLowerCase()}`, newStatus),
                }),
              );
            }
          },
          onError: (err) => {
            toast.error(
              extractApiError(
                err,
                t("detail.status_change_failed", "Status change failed"),
              ),
            );
          },
        },
      );
    },
    [id, bulkEditAssets, t],
  );

  return { changeStatus, isPending };
}
