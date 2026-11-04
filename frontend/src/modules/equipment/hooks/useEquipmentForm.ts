import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { itemsApi } from "@/lib/api/items";
import { labelsApi } from "@/lib/api/labels";
import { invalidation } from "@/lib/api/invalidation";
import { extractApiError, followUpError } from "@/lib/errors";
import type { EquipmentModel } from "@/modules/equipment/api/equipment";
import type { FieldDefinition, ItemCreate, ItemUpdate } from "@/types";
import type { EquipmentFormData } from "@/modules/equipment/pages/AddEquipmentPage";
import { useEquipmentImageUpload } from "@/modules/equipment/hooks/useEquipmentImageUpload";
import { useEquipmentBulkCreate } from "@/modules/equipment/hooks/useEquipmentBulkCreate";
import { formatModelDisplayName } from "@/modules/equipment/components/assetUtils";
import { useAllCategories } from "@/modules/shared/hooks/useCategories";

// These keys are owned by the dedicated "Purchase &
// Warranty" card and the notes field. They must never render again as
// dynamic fields from the category card — two editable inputs writing to
// the same meta key caused a silent last-writer-wins overwrite.
export const DEDICATED_KEYS: ReadonlySet<string> = new Set([
  "notes",
  "purchase_date",
  "warranty_until",
]);

/**
 * Category-declared field that is stored as a core column, not in the
 * equipment namespace.
 *
 * The serial number identifies the asset, so it belongs where the core
 * search can reach it — a number typed into the command palette used to
 * find nothing while the module's own list found it at once. The field
 * still renders from the category declaration; only its destination
 * changed.
 */
const SERIAL_KEY = "serial_number";
const MODEL_KEY = "model_id";

/** Drop category-declared fields that are owned by dedicated form cards. */
export function filterDedicatedFields(
  fields: FieldDefinition[],
): FieldDefinition[] {
  return fields.filter((f) => !DEDICATED_KEYS.has(f.key));
}

interface LocationState {
  labelCode?: string;
  template?: {
    name?: string;
    brand?: string | null;
    location_id?: string | null;
    category_id?: string | null;
  };
}

const EMPTY_FORM: EquipmentFormData = {
  name: "",
  category_id: "",
  location_id: "",
  barcode: "",
  label_code: "",
  purchase_price: "",
  purchase_date: "",
  warranty_until: "",
  notes: "",
  dynamic: {},
};

export function useEquipmentForm(
  editItemId: string | undefined,
  state: LocationState,
) {
  const { t } = useTranslation("equipment");
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [form, setForm] = useState<EquipmentFormData>(() => ({
    ...EMPTY_FORM,
    name: state.template?.name ?? "",
    location_id: state.template?.location_id ?? "",
    category_id: state.template?.category_id ?? "",
  }));
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<
    Partial<Record<"name" | "location_id" | "category_id", string>>
  >({});
  const [isFetchingItem, setIsFetchingItem] = useState(Boolean(editItemId));
  // A failed read used to leave the form standing and empty, with a live
  // Save button — so the first save wrote that emptiness over the record.
  // The failure is state now, and the page renders it instead of the form.
  const [loadError, setLoadError] = useState<unknown>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [selectedModelId, setSelectedModelId] = useState("");
  const skipCategoryReset = useRef(false);
  // Tracks the label_code the item had when loaded for editing, so we can
  // detect whether the user changed it and reconcile the LabelPool binding.
  const originalLabelCode = useRef<string>("");

  const image = useEquipmentImageUpload();

  // The asset list asks whether an item is equipment; a category is how the
  // organization says so, and it carries the fields this form then renders. So
  // the category is required — but only once there is one to pick, or the
  // first asset could never be created.
  //
  // A category list that failed to arrive cannot say there is nothing to pick:
  // the stricter answer holds, so Enter in a field does not file an asset
  // without a category the page then cannot show.
  const { data: allCategories = [], isError: categoriesFailed } =
    useAllCategories();
  const categoryRequired =
    categoriesFailed ||
    allCategories.some((c) => c.context_tag === "equipment");

  const isEditMode = Boolean(editItemId);

  // Pre-fill form when editing an existing item
  useEffect(() => {
    if (!editItemId) return;
    let cancelled = false;
    setIsFetchingItem(true);
    setLoadError(null);
    itemsApi
      .getById(editItemId)
      .then((item) => {
        if (cancelled) return;
        const equip = (item.metadata?.equipment ?? {}) as Record<
          string,
          unknown
        >;
        const dynamic: Record<string, string> = {};
        for (const [k, v] of Object.entries(equip)) {
          if (!DEDICATED_KEYS.has(k)) dynamic[k] = String(v ?? "");
        }
        if (item.serial_number) dynamic[SERIAL_KEY] = item.serial_number;
        skipCategoryReset.current = true;
        if (item.image_url) image.setCurrentImageUrl(item.image_url);
        originalLabelCode.current = item.label_code ?? "";
        setForm({
          name: item.name,
          category_id: item.category_id ?? "",
          location_id: item.location_id,
          barcode: item.barcode ?? "",
          label_code: item.label_code ?? "",
          purchase_price:
            item.purchase_price != null ? String(item.purchase_price) : "",
          purchase_date: String(equip.purchase_date ?? ""),
          warranty_until: String(equip.warranty_until ?? ""),
          notes: String(equip.notes ?? ""),
          dynamic,
        });
        setIsFetchingItem(false);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          // No toast: the page puts the same message where the form was, and
          // a toast that expires would be the only trace of a screen the
          // reader is otherwise entitled to believe holds their record.
          setLoadError(err);
          setIsFetchingItem(false);
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editItemId, reloadToken]);

  // Reset dynamic fields when category changes (skip during edit pre-fill)
  useEffect(() => {
    if (skipCategoryReset.current) {
      skipCategoryReset.current = false;
      return;
    }
    setForm((prev) => ({ ...prev, dynamic: {} }));
  }, [form.category_id]);

  const set = (field: keyof EquipmentFormData, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }));
    setFieldErrors((prev) => {
      if (!(field in prev)) return prev;
      const next = { ...prev };
      delete next[field as keyof typeof next];
      return next;
    });
  };

  const setDynamic = (key: string, value: unknown) => {
    setForm((prev) => ({
      ...prev,
      dynamic: { ...prev.dynamic, [key]: value },
    }));
  };

  const buildMeta = () => {
    const equipmentMeta: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(form.dynamic)) {
      // Skip empty strings but keep arrays/booleans/money objects.
      if (v === "" || v === null || v === undefined) continue;
      if (k === SERIAL_KEY) continue;
      equipmentMeta[k] = v;
    }
    if (form.notes) equipmentMeta.notes = form.notes;
    if (form.purchase_date) equipmentMeta.purchase_date = form.purchase_date;
    if (form.warranty_until) equipmentMeta.warranty_until = form.warranty_until;
    return equipmentMeta;
  };

  // The asset is saved before its photo goes up. A photo that fails then is
  // reported as that — never as the asset "not saved", which would invite a
  // second, duplicate asset.
  const applyImageAfterSave = async (itemId: string) => {
    try {
      await image.applyImageChanges(itemId);
    } catch (err) {
      toast.error(
        followUpError(
          err,
          t("items:messages.fileUploadFailed", "Failed to upload file"),
        ),
      );
    }
  };

  // The required fields, marked inline (the page moves focus to the first one)
  // and named in a toast. Shared by the single and the batch submit; a batch
  // takes its name from "Asset" when blank, so only the single one needs it.
  const validateRequired = ({ name }: { name: boolean }) => {
    const errors: Partial<
      Record<"name" | "location_id" | "category_id", string>
    > = {};
    if (name && !form.name.trim()) {
      errors.name = t("form.errors.nameRequired", "Name is required");
    }
    if (!form.location_id) {
      errors.location_id = t(
        "form.errors.locationRequired",
        "Location is required",
      );
    }
    if (categoryRequired && !form.category_id) {
      errors.category_id = t(
        "form.errors.categoryRequired",
        "Category is required",
      );
    }
    setFieldErrors(errors);
    const firstError = errors.name ?? errors.category_id ?? errors.location_id;
    if (firstError) toast.error(firstError);
    return !firstError;
  };

  const bulk = useEquipmentBulkCreate(form, buildMeta, () =>
    validateRequired({ name: false }),
  );

  const handleModelSelect = (models: EquipmentModel[], modelId: string) => {
    setSelectedModelId(modelId);
    if (!modelId) {
      // Back to "create from scratch": the unit no longer belongs to a model,
      // so it must stop borrowing its picture.
      setForm((prev) => {
        const { [MODEL_KEY]: _released, ...rest } = prev.dynamic;
        return { ...prev, dynamic: rest };
      });
      return;
    }
    const model = models.find((m) => m.id === modelId);
    if (!model) return;
    // The reset effect only runs, and so only clears the flag, when the
    // category really changes; set otherwise it would swallow the user's next
    // category choice.
    if (model.category_id && model.category_id !== form.category_id) {
      skipCategoryReset.current = true;
    }
    const newDynamic: Record<string, string> = {};
    for (const [k, v] of Object.entries(model.equipment_meta ?? {})) {
      if (v != null && v !== "") newDynamic[k] = String(v);
    }
    // The model's brand and name are the manufacturer and model the form asks
    // for as text; its own meta wins when it records them.
    if (model.brand?.trim()) newDynamic.manufacturer ??= model.brand.trim();
    if (model.name.trim()) newDynamic.model ??= model.name.trim();
    // Remembered so the unit can fall back to the model's picture: a batch is
    // created in one call with nowhere to upload one photo per unit.
    newDynamic[MODEL_KEY] = model.id;
    setForm((prev) => ({
      ...prev,
      name: formatModelDisplayName(model),
      category_id: model.category_id ?? prev.category_id,
      dynamic: { ...newDynamic },
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!validateRequired({ name: true })) return;

    const equipmentMeta = buildMeta();
    const serialNumber = String(form.dynamic[SERIAL_KEY] ?? "").trim();

    setIsSubmitting(true);
    try {
      if (isEditMode && editItemId) {
        const updatePayload: ItemUpdate = {
          name: form.name.trim(),
          category_id: form.category_id || null,
          barcode: form.barcode.trim() || null,
          purchase_price: form.purchase_price
            ? Number(form.purchase_price)
            : null,
          serial_number: serialNumber || null,
          metadata: { equipment: equipmentMeta },
          // The form never changes the unit against the template, which is
          // the flag's "no" — the answer the server used to default to.
          unit_confirmed_over_template: false,
        };
        await itemsApi.update(editItemId, updatePayload);
        await applyImageAfterSave(editItemId);
        // Reconcile label_code through the label-pool API rather than the
        // generic item PATCH: the LabelPool binding (is_assigned / item_id)
        // must stay consistent with Item.label_code. assign also frees the
        // previously bound label; unassign releases it when cleared.
        const newLabelCode = form.label_code.trim();
        if (newLabelCode !== originalLabelCode.current) {
          if (newLabelCode) {
            try {
              await labelsApi.assignToExistingItem(newLabelCode, editItemId);
            } catch {
              toast.error(
                t(
                  "form.labelAssignFailed",
                  "Asset saved but label not assigned",
                ),
              );
            }
          } else if (originalLabelCode.current) {
            try {
              await labelsApi.unassign(originalLabelCode.current);
            } catch {
              /* non-fatal: item is already saved */
            }
          }
        }
        // Invalidate the detail + list queries so the next page load fetches
        // the freshly persisted item (including image_url). Without this,
        // React Query's 5-minute staleTime serves the pre-edit cached item
        // (image_url still null), so the uploaded image never renders.
        invalidation.equipment(queryClient);
        toast.success(t("form.updated", "Asset updated successfully"));
        navigate(`/equipment/${editItemId}`);
      } else {
        const payload: ItemCreate = {
          name: form.name.trim(),
          location_id: form.location_id,
          category_id: form.category_id || undefined,
          barcode: form.barcode || undefined,
          template_id: selectedModelId || undefined,
          purchase_price: form.purchase_price
            ? Number(form.purchase_price)
            : undefined,
          quantity: 1,
          serial_number: serialNumber || undefined,
          // Always send the namespace, even empty: the module's interceptor
          // seeds equipment_status from it, and an asset created under a
          // category that declares no status field would otherwise carry
          // none — invisible under every status chip on the list.
          metadata: { equipment: equipmentMeta },
          // Quantity 1 with no template match to contradict — the flag's
          // "no", which the server used to default to.
          unit_confirmed_over_template: false,
        };

        const created = await itemsApi.create(payload);

        await applyImageAfterSave(created.id);

        const labelToAssign = state.labelCode || form.label_code.trim();
        if (labelToAssign) {
          try {
            await labelsApi.assignToExistingItem(labelToAssign, created.id);
          } catch {
            toast.error(
              t("form.labelAssignFailed", "Asset saved but label not assigned"),
            );
          }
        }

        // Invalidate the list so the new item (with its image) appears, and
        // the detail cache is primed fresh instead of a stale entry.
        invalidation.equipment(queryClient);
        toast.success(t("form.created", "Asset added successfully"));
        navigate(`/equipment/${created.id}`);
      }
    } catch (err) {
      // The `{{msg}}` this used to interpolate is in none of the five
      // translations, so the reason was computed and dropped. The server's
      // sentence replaces the generic one instead of decorating it.
      toast.error(extractApiError(err, t("form.errors.saveFailed")));
    } finally {
      setIsSubmitting(false);
    }
  };

  return {
    form,
    set,
    setDynamic,
    fieldErrors,
    categoryRequired,
    handleModelSelect,
    handleSubmit,
    handleBulkSubmit: bulk.handleBulkSubmit,
    downloadBulkLabels: bulk.downloadBulkLabels,
    clearBulkLabelResult: bulk.clearBulkLabelResult,
    isSubmitting,
    isBulkSubmitting: bulk.isBulkSubmitting,
    isFetchingItem,
    loadError,
    retryLoad: () => setReloadToken((token) => token + 1),
    isDownloadingLabels: bulk.isDownloadingLabels,
    isEditMode,
    selectedModelId,
    currentImageUrl: image.currentImageUrl,
    bulkLabelResult: bulk.bulkLabelResult,
    imageFile: image.imageFile,
    setImageFile: image.setImageFile,
    deleteImageFlag: image.deleteImageFlag,
    setDeleteImageFlag: image.setDeleteImageFlag,
  };
}
