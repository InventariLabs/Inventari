import { extractApiError } from "@/lib/errors";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { labelsApi } from "@/lib/api/labels";
import { equipmentApi } from "@/modules/equipment/api/equipment";
import { queryKeys } from "@/hooks/queries/keys";
import { downloadBlob } from "@/utils/helpers";
import type { BulkEquipmentEntry } from "@/modules/equipment/api/equipment";
import type { EquipmentFormData } from "@/modules/equipment/pages/AddEquipmentPage";

/**
 * Batch-create flow: creates N assets from serial-number entries, optionally
 * registers one QR label per asset, and offers a combined PNG download of
 * the generated labels before navigating away.
 */
export function useEquipmentBulkCreate(
  form: EquipmentFormData,
  buildMeta: () => Record<string, unknown>,
  /** Marks and names the missing required fields; false refuses the submit. */
  validate: () => boolean,
) {
  const { t } = useTranslation("equipment");
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [isBulkSubmitting, setIsBulkSubmitting] = useState(false);
  // After a batch is created with QR labels, holds the generated label IDs so
  // the UI can offer a combined PNG download before navigating away.
  const [bulkLabelResult, setBulkLabelResult] = useState<{
    labelIds: string[];
    count: number;
    qrOnly: boolean;
  } | null>(null);
  const [isDownloadingLabels, setIsDownloadingLabels] = useState(false);

  const handleBulkSubmit = async (
    entries: BulkEquipmentEntry[],
    options?: { assignLabels?: boolean; qrOnly?: boolean },
  ) => {
    if (!validate()) return;

    const equipmentMeta = buildMeta();
    const assetName = form.name.trim() || t("bulk.defaultName", "Asset");

    setIsBulkSubmitting(true);
    try {
      const result = await equipmentApi.bulkCreateItems({
        name: assetName,
        category_id: form.category_id || undefined,
        location_id: form.location_id,
        brand: undefined,
        purchase_price: form.purchase_price
          ? Number(form.purchase_price)
          : undefined,
        metadata:
          Object.keys(equipmentMeta).length > 0
            ? { equipment: equipmentMeta }
            : undefined,
        entries,
      });

      if (result.failed === 0) {
        toast.success(
          t("bulk.success", "Created {{count}} items", {
            count: result.created,
          }),
        );
      } else {
        toast.success(
          t("bulk.partial", "Created {{created}}, failed {{failed}}", {
            created: result.created,
            failed: result.failed,
          }),
        );
      }

      // Optionally register one QR label per asset whose short_code IS the
      // serial number (so the sticker is meaningful and scannable). Only when
      // every item was created — otherwise the serial↔item index mapping is
      // ambiguous. Labels come from the shared LabelPool (no duplicates).
      if (
        options?.assignLabels &&
        result.failed === 0 &&
        result.items.length > 0
      ) {
        try {
          const codes = entries
            .map((e) => e.serial_number.trim())
            .filter(Boolean)
            .map((shortCode) => ({
              short_code: shortCode,
              description: options.qrOnly ? undefined : assetName,
            }));
          const labels = await labelsApi.createFromCodes({
            codes,
            label_type: "EQUIPMENT",
          });
          await Promise.all(
            labels.map((lbl, index) =>
              labelsApi.assignToExistingItem(
                lbl.short_code,
                result.items[index],
              ),
            ),
          );
          queryClient.invalidateQueries({ queryKey: queryKeys.labels.all });
          queryClient.invalidateQueries({
            queryKey: queryKeys.equipment.assets.all,
          });
          setBulkLabelResult({
            labelIds: labels.map((l) => l.id),
            count: labels.length,
            qrOnly: Boolean(options.qrOnly),
          });
          return;
        } catch {
          toast.error(
            t(
              "bulk.labelAssignFailed",
              "Items created, but QR labels could not be assigned",
            ),
          );
        }
      }

      navigate("/equipment");
    } catch (error) {
      toast.error(
        extractApiError(
          error,
          t("form.errors.saveFailed", "Failed to create items"),
        ),
      );
    } finally {
      setIsBulkSubmitting(false);
    }
  };

  const downloadBulkLabels = async () => {
    if (!bulkLabelResult) return;
    setIsDownloadingLabels(true);
    try {
      const blob = await labelsApi.exportPng({
        count: bulkLabelResult.count,
        labelIds: bulkLabelResult.labelIds,
        width: 50,
        height: 24,
        qrOnly: bulkLabelResult.qrOnly || undefined,
      });
      downloadBlob(blob, `equipment_labels_${bulkLabelResult.count}pcs.png`);
    } catch (error) {
      toast.error(
        extractApiError(
          error,
          t("qr.downloadFailed", "Failed to download QR labels"),
        ),
      );
    } finally {
      setIsDownloadingLabels(false);
    }
  };

  const clearBulkLabelResult = () => setBulkLabelResult(null);

  return {
    handleBulkSubmit,
    downloadBulkLabels,
    clearBulkLabelResult,
    isBulkSubmitting,
    isDownloadingLabels,
    bulkLabelResult,
  };
}
