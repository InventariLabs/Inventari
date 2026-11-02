import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ArchiveX, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { ActionMenu } from "@/components/ui/ActionMenu";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { TypedSlot } from "@/components/Slot";
import { extractApiError } from "@/lib/errors";
import { storagesApi } from "@/lib/api/storages";
import { downloadBlob } from "@/utils/helpers";
import { useStorageEditForm } from "@/modules/spaces/hooks/useStorageEditForm";
import { useStorageTypes } from "@/modules/shared/hooks/useStorages";
import { LocationMoveQuestion } from "@/modules/spaces/components/LocationMoveQuestion";
import { useLocationsById } from "@/module-sdk";
import { useLocationsInside } from "@/modules/spaces/hooks/useLocationsInside";
import { StorageArchiveDialog } from "./StorageArchiveDialog";
import { StorageEditFields } from "./StorageEditFields";
import type { StorageLocation, StorageLocationSummary } from "@/types";

interface StorageSettingsTabProps {
  storage: StorageLocation;
  /** The row the lists show for this location (path, inherited fields). */
  summary: StorageLocationSummary;
  canWrite: boolean;
  onDeleted: () => void;
}

/**
 * A location's settings on the page: basic fields, the product fields it
 * applies to what stands there, its label and code, and the warehouse facts
 * a WMS module reads — one Save for all of them.
 *
 * This is the Edit dialog's field set in place. The dialog could only ever
 * edit one location at a time behind a scrim, and a location that held both
 * locations and products had no place to say what its own products record.
 */
export function StorageSettingsTab({
  storage,
  summary,
  canWrite,
  onDeleted,
}: StorageSettingsTabProps) {
  const { t } = useTranslation(["locations", "common"]);
  const [isGeneratingCode, setIsGeneratingCode] = useState(false);
  const [isArchiveOpen, setIsArchiveOpen] = useState(false);

  const {
    data: storageTypes = [],
    error: typesError,
    refetch: refetchTypes,
  } = useStorageTypes();

  // The record's own type stays choosable when the picker no longer offers
  // it — the type left the list because its module is off or it retired, and
  // the rows stay standing under locations.
  const typeOptions = useMemo(() => {
    const own = storage.location_type;
    if (!own || storageTypes.some((type) => type.id === own.id)) {
      return storageTypes;
    }
    return [...storageTypes, own];
  }, [storageTypes, storage.location_type]);

  const {
    formData,
    setFormData,
    updateMutation,
    deleteMutation,
    confirmDialogProps,
    moveQuestion,
    fieldBuilderRef,
    handleSave,
    handleDelete,
  } = useStorageEditForm(true, storage, summary, () => undefined, onDeleted);
  const insideCount = useLocationsInside(summary);
  // The reader without write access sees the name of the place it lies in.
  const parent = useLocationsById(
    canWrite || !storage.parent_id ? [] : [storage.parent_id],
  );

  const warehouseStrip = {
    storageId: storage.id,
    storageName: storage.name,
    fullPath: summary.full_path ?? null,
    sequence: storage.sequence ?? null,
  };

  const handleGenerateCode = async () => {
    setIsGeneratingCode(true);
    try {
      const updated = await storagesApi.generateCode(storage.id);
      setFormData((prev) => ({
        ...prev,
        short_code: updated.short_code ?? "",
      }));
    } catch (error) {
      toast.error(
        extractApiError(error, t("locations:edit.generateCodeError")),
      );
    } finally {
      setIsGeneratingCode(false);
    }
  };

  const handleQrDownload = async () => {
    try {
      const blob = await storagesApi.printLabel(
        storage.id,
        undefined,
        formData.label_show_description,
      );
      downloadBlob(blob, `qr_${formData.short_code || storage.name}.png`);
    } catch (error) {
      toast.error(extractApiError(error, t("locations:edit.qrDownloadError")));
    }
  };

  if (!canWrite) {
    const parentName = parent.byId.get(storage.parent_id ?? "")?.name ?? "—";
    return (
      <div className="space-y-6">
        <Card className="space-y-4">
          <h3 className="text-sm font-semibold text-on">
            {t("locations:settings.basic")}
          </h3>
          <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
            {[
              [t("locations:edit.nameLabel"), storage.name],
              [
                t("locations:onboarding.storageTypeLabel"),
                storage.location_type?.name ?? "—",
              ],
              [t("locations:settings.liesIn"), parentName],
              [
                t("locations:onboarding.descriptionLabel"),
                storage.description || "—",
              ],
              [t("locations:form.location"), storage.location_details || "—"],
            ].map(([label, value]) => (
              <div key={label}>
                <dt className="text-[10px] font-medium uppercase tracking-widest text-on-muted">
                  {label}
                </dt>
                <dd className="text-on">{value}</dd>
              </div>
            ))}
          </dl>
        </Card>
        <TypedSlot name="storage_warehouse_strip" data={warehouseStrip} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Card className="space-y-6">
        <StorageEditFields
          formData={formData}
          setFormData={setFormData}
          fieldBuilderRef={fieldBuilderRef}
          storageTypes={typeOptions}
          typesError={typesError}
          onRetryTypes={() => void refetchTypes()}
          locationId={storage.id}
          isGeneratingCode={isGeneratingCode}
          onGenerateCode={() => void handleGenerateCode()}
          onQrDownload={() => void handleQrDownload()}
          inherited={summary}
          insideCount={insideCount}
          t={t}
        />
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-4">
          <ActionMenu
            label={t("locations:settings.recordActions", {
              name: storage.name,
            })}
            actions={[
              {
                id: "archive",
                label: t("locations:edit.archive"),
                icon: <ArchiveX size={16} />,
                onSelect: () => setIsArchiveOpen(true),
              },
              {
                id: "delete",
                label: t("common:actions.delete"),
                icon: <Trash2 size={16} />,
                destructive: true,
                disabled: deleteMutation.isPending,
                onSelect: () => void handleDelete(),
              },
            ]}
          />
          <Button
            onClick={handleSave}
            disabled={!formData.name.trim() || updateMutation.isPending}
            leftIcon={<Save size={16} />}
          >
            {updateMutation.isPending
              ? t("common:actions.saving")
              : t("common:actions.save")}
          </Button>
        </div>
      </Card>

      <TypedSlot name="storage_warehouse_strip" data={warehouseStrip} />

      <TypedSlot
        name="storage_detail_extra"
        data={{
          storageId: storage.id,
          storageTypeCode: storage.location_type?.type_code,
        }}
      />

      <ConfirmDialog {...confirmDialogProps} />
      <LocationMoveQuestion {...moveQuestion} />
      <StorageArchiveDialog
        open={isArchiveOpen}
        storageId={storage.id}
        onOpenChange={setIsArchiveOpen}
        onArchived={() => {
          setIsArchiveOpen(false);
          onDeleted();
        }}
      />
    </div>
  );
}
