import { useState, useEffect } from "react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { useConfirm } from "@/hooks/useConfirm";
import { useFieldBuilderCommit } from "@/components/ui/FieldBuilder";
import { extractApiError, extractApiErrorCode } from "@/lib/errors";
import type {
  StorageLocation,
  FieldDefinition,
  StorageLocationSummary,
} from "@/types";
import {
  useUpdateStorage,
  useDeleteStorage,
} from "@/modules/shared/hooks/useStorageMutations";
import { useMoveQuestion } from "@/modules/spaces/hooks/useMoveQuestion";
import { locationDeleteConsequences } from "@/modules/shared/lib/locationDelete";
import type { StorageReorgOperation } from "@/lib/api/storages";

export interface StorageEditFormData {
  name: string;
  description: string;
  /** Free text for where exactly the thing stands ("second shelf, by the door"). */
  location_details: string;
  parent_id: string | null;
  context_schema: string[];
  field_definitions: FieldDefinition[];
  short_code: string;
  label_show_description: boolean;
  /** Stock here fills pick faces; nothing replenishes it from another shelf. */
  is_reserve: boolean;
  location_type_id: string | null;
}

function buildInitialFormData(storage: StorageLocation): StorageEditFormData {
  return {
    name: storage.name,
    description: storage.description || "",
    location_details: storage.location_details || "",
    parent_id: storage.parent_id || null,
    context_schema: storage.context_schema || [],
    field_definitions: storage.field_definitions || [],
    short_code: storage.short_code || "",
    label_show_description:
      (storage.settings?.label_show_description as boolean) ?? true,
    is_reserve: storage.settings?.is_reserve === true,
    location_type_id: storage.location_type_id || null,
  };
}

export function useStorageEditForm(
  open: boolean,
  editingStorage: StorageLocation,
  /** The row the lists show for it: what the delete question counts. */
  row: StorageLocationSummary | undefined,
  onClose: () => void,
  onDeleteSuccess: () => void,
) {
  const { t } = useTranslation(["locations", "common"]);
  const { confirm, confirmDialogProps } = useConfirm();
  const moveQuestion = useMoveQuestion();

  const [formData, setFormData] = useState<StorageEditFormData>(() =>
    buildInitialFormData(editingStorage),
  );

  useEffect(() => {
    if (open) {
      setFormData(buildInitialFormData(editingStorage));
    }
  }, [open, editingStorage]);

  const fieldBuilder = useFieldBuilderCommit(formData.field_definitions);

  const updateMutation = useUpdateStorage();
  const deleteMutation = useDeleteStorage();

  function handleSave() {
    if (!formData.name.trim()) return;
    // A field typed into the builder and not confirmed is part of what the
    // reader is saving: it joins the list, or the save waits for them to
    // finish it.
    const fieldDefinitions = fieldBuilder.commit();
    if (!fieldDefinitions) return;
    if (formData.parent_id !== (editingStorage.parent_id ?? null)) {
      void askWhetherItMovedThenSave(fieldDefinitions);
      return;
    }
    save(undefined, fieldDefinitions);
  }

  /**
   * A location filed under another parent asks, when it holds stock, whether
   * it physically moved; backing out keeps the sheet open as typed.
   */
  async function askWhetherItMovedThenSave(
    fieldDefinitions: FieldDefinition[],
  ) {
    try {
      const answered = await moveQuestion.ask([
        { op: "move", id: editingStorage.id, parent_id: formData.parent_id },
      ]);
      if (answered) save(answered[0]?.relocation, fieldDefinitions);
    } catch (err: unknown) {
      toast.error(extractApiError(err, t("common:errors.actionFailed")));
    }
  }

  function save(
    relocation: StorageReorgOperation["relocation"],
    fieldDefinitions: FieldDefinition[],
  ) {
    const { short_code, label_show_description, is_reserve, ...rest } =
      formData;
    const payload = {
      ...rest,
      field_definitions: fieldDefinitions,
      ...(relocation ? { relocation } : {}),
      ...(short_code ? { short_code } : {}),
      settings: {
        ...(editingStorage.settings || {}),
        label_show_description,
        is_reserve,
      },
    };
    updateMutation.mutate(
      { id: editingStorage.id, data: payload },
      {
        onSuccess: () => {
          toast.success(t("messages.storageUpdated"));
          onClose();
        },
        // A collision is a 409 carrying its own code, so the reader gets a
        // sentence in their own language. Before this the screen relayed the
        // service's English one, which is what a status code is for.
        onError: (err: unknown) => {
          const code = extractApiErrorCode(err);
          if (code === "STORAGE_CONFLICT") {
            toast.error(
              t("messages.nameTaken", { name: formData.name.trim() }),
            );
          } else if (code === "STORAGE_SHORT_CODE_CONFLICT") {
            toast.error(t("messages.shortCodeTaken"));
          } else {
            toast.error(extractApiError(err, t("common:errors.actionFailed")));
          }
        },
      },
    );
  }

  async function handleDelete() {
    const message =
      t("locations:edit.deleteMessage", { name: editingStorage.name }) +
      locationDeleteConsequences(t, row);
    if (
      await confirm({
        title: t("common:actions.delete"),
        message,
        variant: "danger",
        confirmLabel: t("common:actions.delete"),
      })
    ) {
      deleteMutation.mutate(editingStorage.id, {
        onSuccess: () => {
          toast.success(t("messages.storageDeleted"));
          onDeleteSuccess();
        },
        onError: (err: unknown) => {
          toast.error(extractApiError(err, t("locations:errors.cannotDelete")));
        },
      });
    }
  }

  return {
    formData,
    setFormData,
    updateMutation,
    deleteMutation,
    confirmDialogProps,
    confirm,
    moveQuestion: moveQuestion.questionProps,
    fieldBuilderRef: fieldBuilder.ref,
    handleSave,
    handleDelete,
  };
}
