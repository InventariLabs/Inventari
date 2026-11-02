import { useCallback, useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { X, Trash2, Package, AlertCircle } from "lucide-react";
import { attachmentsApi } from "@/lib/api/attachments";
import { itemsApi } from "@/lib/api/items";
import { productTemplatesApi } from "@/lib/api/productTemplates";
import type { ProductTemplate } from "@/lib/api/productTemplates";
import LoadingSpinner from "@/components/LoadingSpinner";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
import { useFocusTrap } from "@/hooks/useFocusTrap";
import { ActionMenu } from "@/components/ui/ActionMenu";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { SheetActions, SheetFooter } from "@/components/ui/Sheet";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useHasPermission } from "@/hooks/useHasPermission";
import { ModalShell } from "@/components/ui/ModalShell";
import { FormSheetFooter } from "@/components/ui/FormSheetFooter";
import ProductFormContent from "./items/ProductFormContent";
import { StockThresholdSection } from "./items/StockThresholdSection";
import { ValuationSection } from "./items/ValuationSection";
import { DeleteReasonDialog } from "./DeleteReasonDialog";
import { Slot } from "@/components/Slot";
import {
  useItemForm,
  type ItemFormData,
} from "@/modules/inventory/hooks/useItemForm";
import { useItem } from "@/modules/inventory/hooks/useItems";
import { useFreeLabel } from "@/modules/inventory/hooks/useFreeLabel";
import { useScopedCategories } from "@/modules/shared/hooks/useCategories";
import {
  useUpdateItem,
  useDeleteItem,
} from "@/modules/inventory/hooks/useItemMutations";

/** The product a record is a card of, read for the valuation section. */
function useProductTemplate(templateId: string | null | undefined) {
  const [template, setTemplate] = useState<ProductTemplate | null>(null);
  const [isLoadingTemplate, setIsLoadingTemplate] = useState(false);
  useEffect(() => {
    if (templateId) {
      setIsLoadingTemplate(true);
      productTemplatesApi
        .get(templateId)
        .then(setTemplate)
        .catch(() => setTemplate(null))
        .finally(() => setIsLoadingTemplate(false));
    } else {
      setTemplate(null);
    }
  }, [templateId]);
  return { template, isLoadingTemplate };
}

/** The sheet's action row: Close and Save to an account that may change the
 * product, Close alone to one that may only read it. */
function ItemEditFooter({
  canWrite,
  isPending,
  onClose,
  onSubmit,
}: {
  canWrite: boolean;
  isPending: boolean;
  onClose: () => void;
  onSubmit: (event: React.FormEvent) => void;
}) {
  const { t } = useTranslation(["items", "common"]);
  if (canWrite) {
    return (
      <FormSheetFooter
        isPending={isPending}
        lineCount={0}
        cancelText={t("common:actions.close")}
        submitText={t("actions.save")}
        onCancel={onClose}
        onSubmit={onSubmit}
      />
    );
  }
  return (
    <SheetFooter>
      <SheetActions>
        <Button type="button" variant="outline" onClick={onClose}>
          {t("common:actions.close")}
        </Button>
      </SheetActions>
    </SheetFooter>
  );
}

/** Deleting and freeing the label speak about the record, not about the edit
 * in progress, so they sit in the header's menu rather than under Save (§4.3).
 * A label put on the wrong product is put right from here, where its code is
 * shown. */
function ItemRecordMenu({
  onDelete,
  onFreeLabel,
}: {
  onDelete?: () => void;
  onFreeLabel?: () => void;
}) {
  const { t } = useTranslation(["items", "common", "labels"]);
  const actions = [];
  if (onFreeLabel) {
    actions.push({
      id: "free-label",
      label: t("labels:actions.freeLabel"),
      onSelect: onFreeLabel,
    });
  }
  if (onDelete) {
    actions.push({
      id: "delete",
      label: t("deleteItem"),
      icon: <Trash2 size={16} />,
      destructive: true,
      onSelect: onDelete,
    });
  }
  if (actions.length === 0) return null;
  return <ActionMenu label={t("common:actions.more")} actions={actions} />;
}

/** What the sheet says when the product cannot be loaded or no longer exists. */
function ItemNotFound({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation(["items", "common"]);
  return (
    <ModalShell
      open
      onClose={onClose}
      layout="centered"
      className="!animate-none"
    >
      <div
        className="bg-surface-card rounded-2xl shadow-lg max-w-md w-full p-6 text-center space-y-4"
        role="dialog"
        aria-modal="true"
        aria-labelledby="item-not-found-title"
      >
        <div className="w-14 h-14 rounded-2xl bg-amber-50 flex items-center justify-center mx-auto">
          <AlertCircle size={28} className="text-amber-500" />
        </div>
        <h2 id="item-not-found-title" className="text-lg font-semibold text-on">
          {t("items:itemNotFound", {
            defaultValue: "Item could not be loaded",
          })}
        </h2>
        <p className="text-sm text-on-secondary">
          {t("items:itemNotFoundDescription")}
        </p>
        <Button onClick={onClose} className="w-full">
          {t("common:actions.backToList")}
        </Button>
      </div>
    </ModalShell>
  );
}

interface ItemEditModalProps {
  itemId: string;
  onClose: () => void;
}

export default function ItemEditModal({ itemId, onClose }: ItemEditModalProps) {
  const { t } = useTranslation(["items", "categories", "common", "labels"]);

  // A reader without `items:write` opens the same sheet to *read* the
  // product: the fields stay, nothing can be typed into them and there is no
  // Save to answer 403 after the work. Deleting is its own key, as in the list.
  const canWrite = useCanWrite("items");
  const canDelete = useHasPermission("items:delete");
  const { dialogState, closeDialog } = useConfirmDialog();
  const {
    freeLabel,
    isFreeing,
    confirmDialogProps: freeDialog,
  } = useFreeLabel();
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [showDeleteReason, setShowDeleteReason] = useState(false);
  /** Where the reader asked to go, held while we ask about unsaved edits. */
  const [pendingLeave, setPendingLeave] = useState<(() => void) | null>(null);
  const modalRef = useFocusTrap(
    !dialogState.isOpen &&
      !showDeleteReason &&
      pendingLeave === null &&
      !freeDialog.open,
  );

  const {
    data: item,
    isLoading: isLoadingItem,
    isError: isItemError,
  } = useItem(itemId);

  useEffect(() => {
    if (item?.image_url) {
      setImagePreview(item.image_url);
    }
  }, [item]);

  const { template, isLoadingTemplate } = useProductTemplate(item?.template_id);

  // The picker offers the scope the product list shows, with the record's
  // own category kept in — an asset opened for editing must still see the
  // category it is filed under, or the field would show a placeholder over
  // a value the save would then carry anyway.
  const { scoped: categories } = useScopedCategories(item?.category_id ?? null);
  // The item's own location is kept whatever owns it — the location field
  // names the place by id, so a record opened for editing still shows the
  // place it stands — and the rest of the offer is a stock flow's: what may
  // hold stock, never a place a module owns. An asset filed in a rack keeps
  // its rack; picking a different rack belongs to the equipment module's own
  // screen, which lists the module's locations.

  const updateItemMutation = useUpdateItem();

  const updateMutation = {
    mutate: (data: Record<string, unknown>) =>
      updateItemMutation.mutate(
        { id: itemId, data },
        {
          onSuccess: () => {
            toast.success(t("messages.updateSuccess"));
            onClose();
          },
          onError: (error: unknown) => {
            setErrors({
              submit: extractApiError(error, t("messages.updateFailed")),
            });
          },
        },
      ),
    isPending: updateItemMutation.isPending,
  };

  const {
    formData,
    isDirty,
    errors,
    setErrors,
    fieldDefinitions,
    handleInputChange,
    submit,
    selectedStorageType,
  } = useItemForm({
    initialData: item as unknown as Partial<ItemFormData>,
    categories,
    onSubmit: (data) => updateMutation.mutate(data),
    form: "item_edit",
  });

  /**
   * Every way out of this form goes through here, so an edit in progress is
   * never lost without a word. A module slot rendered inside the form can
   * navigate away too, which is why this is handed to the slot rather than
   * kept private: the slot has no way to know what the form is holding.
   */
  const requestLeave = useCallback(
    (go: () => void) => {
      if (isDirty) {
        setPendingLeave(() => go);
        return;
      }
      go();
    },
    [isDirty],
  );

  const requestClose = useCallback(
    () => requestLeave(onClose),
    [requestLeave, onClose],
  );

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") requestClose();
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [requestClose]);

  const handleFileSelect = async (fieldKey: string, file: File) => {
    try {
      const attachment = await attachmentsApi.upload(itemId, file);
      handleInputChange(fieldKey, `/uploads/${attachment.file_path}`, true);
      toast.success(t("items:messages.fileAttached"));
    } catch (error) {
      toast.error(extractApiError(error, t("items:messages.fileUploadFailed")));
    }
  };

  const handleImageSelect = async (file: File) => {
    try {
      const { image_url } = await itemsApi.uploadImage(itemId, file);
      setImagePreview(image_url);
    } catch (error) {
      toast.error(extractApiError(error, t("items:messages.fileUploadFailed")));
    }
  };

  const deleteItemMutation = useDeleteItem();
  const deleteMutation = {
    mutate: () => setShowDeleteReason(true),
    isPending: deleteItemMutation.isPending,
  };

  const handleDeleteWithReason = async (reason: string, notes: string) => {
    // Awaited: a refused delete leaves the reason dialog standing with its
    // fields, rather than closing over a record that is still there.
    await deleteItemMutation.mutateAsync({ itemId, reason, notes });
    toast.success(t("messages.deleteSuccess"));
    setShowDeleteReason(false);
    onClose();
  };

  if (isLoadingItem) {
    return (
      <ModalShell open onClose={onClose} backdropOpacity={50} layout="centered">
        <div className="bg-surface-card rounded-xl p-8 shadow-md">
          <LoadingSpinner />
        </div>
      </ModalShell>
    );
  }

  if (isItemError || !item) return <ItemNotFound onClose={onClose} />;

  return (
    <ModalShell open onClose={requestClose} layout="bottom-sheet">
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="edit-modal-title"
        className="flex max-h-[95vh] w-full max-w-md sm:max-w-xl lg:max-w-2xl xl:max-w-3xl flex-col overflow-hidden bg-surface-card shadow-lg animate-in slide-in-from-bottom sm:slide-in-from-bottom-0 sm:zoom-in-95 duration-300 rounded-t-3xl sm:rounded-2xl sm:max-h-[90vh]"
      >
        {/* Header */}
        <div className="z-10 flex shrink-0 items-center justify-between border-b bg-surface-card p-5 rounded-t-3xl sm:rounded-t-2xl">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary-100 text-primary-600">
              <Package size={24} />
            </div>
            <div>
              <h2
                id="edit-modal-title"
                className="text-lg font-semibold leading-tight text-on"
              >
                {canWrite ? t("editItem") : t("viewItem")}
              </h2>
              {item.label_code && (
                <div className="flex items-center gap-1 mt-0.5">
                  <span className="text-[10px] font-medium text-primary-600 bg-primary-50 px-1.5 py-0.5 rounded uppercase tracking-tighter border border-primary-100">
                    {item.label_code}
                  </span>
                </div>
              )}
            </div>
          </div>
          {/* Deleting speaks about the item, not about the edit in progress,
              so it sits with the record's actions rather than under Save
              (§4.3). */}
          <div className="flex items-center gap-1 shrink-0">
            <ItemRecordMenu
              onDelete={canDelete ? () => deleteMutation.mutate() : undefined}
              onFreeLabel={
                canWrite && item.label_code && !isFreeing
                  ? () => void freeLabel(item.label_code!, item.name)
                  : undefined
              }
            />
            <Button
              variant="ghost"
              size="icon"
              onClick={requestClose}
              aria-label={t("common:a11y.close")}
            >
              <X size={24} />
            </Button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          <form id="edit-item-form" onSubmit={submit} className="p-6 space-y-8">
            <ReadOnlyNotice module="items" />

            {errors.submit && (
              <div className="flex items-center gap-2 p-3 bg-red-50 text-red-600 rounded-xl text-sm italic">
                <AlertCircle size={18} />
                <span>{errors.submit}</span>
              </div>
            )}

            {/* One fieldset rather than a `disabled` on every control: the
                next field added is read-only by having been added. */}
            <fieldset
              disabled={!canWrite}
              className="m-0 min-w-0 space-y-8 border-0 p-0"
            >
              <ProductFormContent
                formData={formData}
                onChange={handleInputChange}
                onFileSelect={handleFileSelect}
                onImageSelect={handleImageSelect}
                errors={errors}
                fieldDefinitions={fieldDefinitions}
                categories={categories}
                imagePreview={imagePreview}
                setImagePreview={setImagePreview}
              />

              <StockThresholdSection
                formData={formData}
                onInputChange={handleInputChange}
                sharedProduct={item.template?.organization_id === null}
              />

              <ValuationSection
                template={template}
                isLoading={isLoadingTemplate}
                uomSymbol={
                  formData.uom
                    ? (formData.uom as { symbol: string }).symbol
                    : undefined
                }
                hasTemplate={!!item.template_id}
              />

              {/* Modular Slots */}
              <Slot
                name="item_edit_extra"
                data={{
                  item,
                  formData,
                  handleInputChange,
                  storageType: selectedStorageType,
                  requestLeave,
                }}
              />
            </fieldset>
          </form>
        </div>

        {/* Footer — one row of actions, about this edit only */}
        <ItemEditFooter
          canWrite={canWrite}
          isPending={updateMutation.isPending}
          onClose={requestClose}
          onSubmit={submit}
        />
      </div>

      <ConfirmDialog
        open={dialogState.isOpen}
        onCancel={closeDialog}
        onConfirm={dialogState.onConfirm}
        title={dialogState.title}
        message={dialogState.message}
        confirmLabel={dialogState.confirmText}
        cancelLabel={dialogState.cancelText}
        variant={dialogState.variant}
      />

      <ConfirmDialog
        open={pendingLeave !== null}
        variant="warning"
        title={t("items:unsaved.title")}
        message={t("items:unsaved.message")}
        confirmLabel={t("items:unsaved.discard")}
        onConfirm={() => {
          const go = pendingLeave;
          setPendingLeave(null);
          go?.();
        }}
        onCancel={() => setPendingLeave(null)}
      />

      <ConfirmDialog {...freeDialog} />

      <DeleteReasonDialog
        key={String(showDeleteReason)}
        open={showDeleteReason}
        itemName={item?.name ?? ""}
        onConfirm={handleDeleteWithReason}
        onCancel={() => setShowDeleteReason(false)}
      />
    </ModalShell>
  );
}
