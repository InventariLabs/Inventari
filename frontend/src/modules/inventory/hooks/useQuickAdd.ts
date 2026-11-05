import { useState, useMemo, useRef } from "react";
import { logger } from "@/utils/logger";
import { makeTDynamic } from "@/lib/i18nHelpers";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { apiErrorStatus, extractApiError, followUpError } from "@/lib/errors";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { labelsApi } from "@/lib/api/labels";
import { itemsApi } from "@/lib/api/items";
import { visionApi } from "@/lib/api/vision";
import { attachmentsApi } from "@/lib/api/attachments";
import { useScanStore } from "@/store/scanStore";
import { useModules } from "@/contexts/ModulesContext";
import { compressImage } from "@/lib/imageUtils";
import { useItemForm, ItemFormData } from "./useItemForm";
import { useMissingPicks } from "./useMissingPicks";
import { useFormGuard } from "@/hooks/useFormGuard";
import type {
  Item,
  VisionExtractResult,
  VisionNutritionFields,
  LabelAssignRequest,
  ItemCreate,
} from "@/types";
import {
  QUICK_ADD_STORAGE_SCOPE,
  useQuickAddStorages,
} from "@/modules/inventory/hooks/useQuickAddStorages";
import {
  useAllCategories,
  useScopedCategories,
} from "@/modules/shared/hooks/useCategories";

interface UseQuickAddProps {
  labelCode?: string;
  initialStorageId?: string;
  initialData?: Partial<ItemFormData>;
  contextTag?: string;
  onSuccess: (newItem?: Item) => void;
}

/**
 * The two category lists the form reads, and whether either never arrived.
 *
 * Categories answer two different questions here, and one list cannot
 * answer both. The full catalogue is what the record's own category and
 * the label's purpose are looked up in; the picker offers the scoped set —
 * the same one the product list shows — so a category that would move the
 * record into a module is not handed out by a form that says "product".
 * A category the record deliberately carries — from the caller's
 * initialData, or the one the label's own purpose names — stays offered
 * even when it belongs to a module: it is an ask, not a leftover.
 *
 * The form's fields read the full list and its picker the offered one. A list
 * refreshed in vain still answers both, so only a missing one counts as failed.
 */
function useQuickAddCategories(
  initialCategoryId: string | null | undefined,
  contextTag: string | undefined,
) {
  const {
    data: allCategories,
    error: allCategoriesError,
    refetch: refetchAllCategories,
  } = useAllCategories();
  const deliberateCategoryId =
    initialCategoryId ??
    (contextTag && allCategories
      ? allCategories.find((c) => c.context_tag === contextTag)?.id
      : undefined) ??
    null;
  const {
    scoped: scopedCategories,
    error: scopedCategoriesError,
    refetch: refetchScopedCategories,
  } = useScopedCategories(deliberateCategoryId);
  const missingListError =
    (!allCategories && allCategoriesError) ||
    (!scopedCategories && scopedCategoriesError);
  const categoriesFailure = missingListError
    ? {
        error: missingListError,
        retry: () => {
          void refetchAllCategories();
          refetchScopedCategories();
        },
      }
    : null;
  return { allCategories, scopedCategories, categoriesFailure };
}

export function useQuickAdd({
  labelCode,
  initialStorageId,
  initialData,
  contextTag,
  onSuccess,
}: UseQuickAddProps) {
  const { t } = useTranslation([
    "scan",
    "common",
    "items",
    "categories",
    "labels",
  ]);
  const tDyn = makeTDynamic(t);
  const {
    lastStorageId,
    lastCategoryId,
    setLastUsed,
    clearLastUsed,
    storageContext,
  } = useScanStore();

  // The form, not the camera. Vision AI opened first, so on a desktop without
  // a camera the first contact with the module's main flow was a dead end —
  // and it depends on a configured LLM besides. The camera is one tab away.
  const [chosenTab, setActiveTab] = useState<"vision" | "manual">("manual");

  // Reading a photo belongs to a module that can be switched off. Where it is
  // off the camera is not one tab away, it is nowhere: the request behind it
  // comes back refused. The screens above hide the tab, and this coerces the
  // state so a stale "vision" cannot survive the module being turned off.
  const { enabledModules } = useModules();
  const visionEnabled = enabledModules.includes("vision");
  const activeTab = visionEnabled ? chosenTab : "manual";

  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [imagePreview, setImagePreview] = useState<string | null>(
    initialData?.image_url ?? null,
  );

  // Queries
  const {
    noStorages,
    hasHidden: hasHiddenStorages,
    isError: isStoragesError,
    refetch: refetchStorages,
  } = useQuickAddStorages();
  const { allCategories, scopedCategories, categoriesFailure } =
    useQuickAddCategories(initialData?.category_id, contextTag);

  const { rememberedStorageId, rememberedCategoryId, heldFromMemory } =
    rememberedPicks(initialData, initialStorageId, {
      storageContext,
      lastStorageId,
      lastCategoryId,
    });

  const pendingFiles = useRef<Record<string, File>>({});
  const pendingImage = useRef<File | null>(null);

  const handleFileSelect = (fieldKey: string, file: File) => {
    pendingFiles.current[fieldKey] = file;
  };

  const handleImageSelect = (file: File) => {
    pendingImage.current = file;
    const reader = new FileReader();
    reader.onloadend = () => setImagePreview(reader.result as string);
    reader.readAsDataURL(file);
  };

  const assignMutation = useAppMutation(
    (data: Partial<ItemCreate>) =>
      labelCode
        ? labelsApi.assign(labelCode, data as LabelAssignRequest)
        : itemsApi.create(data as ItemCreate),
    async (qc, newItem) => {
      // Passing the category straight through: a product saved without one
      // clears the memory rather than leaving it armed for the next form.
      setLastUsed(newItem.location_id, newItem.category_id ?? undefined);

      // Upload any pending file fields as attachments
      const fileEntries = Object.entries(pendingFiles.current);
      if (fileEntries.length > 0) {
        try {
          const uploads = await Promise.all(
            fileEntries.map(async ([fieldKey, file]) => {
              const attachment = await attachmentsApi.upload(newItem.id, file);
              return { fieldKey, url: `/uploads/${attachment.file_path}` };
            }),
          );
          // Persist the file URL back into the item metadata
          const metaUpdates = Object.fromEntries(
            uploads.map(({ fieldKey, url }) => [fieldKey, url]),
          );
          await itemsApi.update(newItem.id, {
            // The contract requires the flag; this write touches metadata
            // only, which is the flag's "no".
            unit_confirmed_over_template: false,
            metadata: { ...newItem.metadata, ...metaUpdates },
          });
        } catch (error) {
          toast.error(
            followUpError(
              error,
              t("items:messages.fileUploadFailedAttachment"),
            ),
          );
        }
        pendingFiles.current = {};
      }

      // Upload pending product image
      if (pendingImage.current) {
        try {
          const { image_url } = await itemsApi.uploadImage(
            newItem.id,
            pendingImage.current,
          );
          setImagePreview(image_url);
        } catch (error) {
          toast.error(
            followUpError(error, t("items:messages.fileUploadFailed")),
          );
        }
        pendingImage.current = null;
      }

      qc.invalidateQueries();
      toast.success(t("labels:quickAdd.success"));
      onSuccess(newItem);
    },
    {
      onError: (error: unknown) => {
        // show a friendly, localized message via the shared mapper
        // instead of the raw pydantic `${loc}: ${msg}` (e.g.
        // "body.quantity: ensure this value is greater than 0") —
        // a 4xx refusal is the toast's job, not the console's.
        if ((apiErrorStatus(error) ?? 500) >= 500) {
          logger.error("[QuickAdd] error:", error);
        }
        toast.error(extractApiError(error, t("labels:quickAdd.error")), {
          duration: 5000,
        });
      },
    },
  );

  const memoizedInitialData = useMemo(() => {
    let categoryId = initialData?.category_id || rememberedCategoryId;

    // Auto-select first category matching contextTag
    if (!categoryId && contextTag && allCategories) {
      const matched = allCategories.find((c) => c.context_tag === contextTag);
      if (matched) categoryId = matched.id;
    }

    return {
      ...initialData,
      name: initialData?.name || "",
      brand: initialData?.brand || "",
      location_id:
        initialData?.location_id ||
        initialStorageId ||
        storageContext?.id ||
        rememberedStorageId,
      category_id: categoryId,
      quantity: "1",
      uom_id: initialData?.uom_id || undefined,
    };
  }, [
    initialData,
    initialStorageId,
    storageContext?.id,
    rememberedStorageId,
    rememberedCategoryId,
    contextTag,
    allCategories,
  ]);

  const {
    formData,
    setFormData,
    isDirty,
    errors,
    setErrors,
    fieldDefinitions,
    handleInputChange,
    handleMetadataChange,
    submit,
    templateUnit,
    pendingUnitChoice,
    resolveUnitChoice,
    storageOffered,
  } = useItemForm({
    initialData: memoizedInitialData,
    categories: allCategories,
    storageScope: QUICK_ADD_STORAGE_SCOPE,
    keepStorageId: initialStorageId ?? null,
    onSubmit: (data) => assignMutation.mutate(data),
  });

  // Both consumers of this hook sit in front of the same gate — the
  // add-product page and QuickAddModal — so the registration lives here,
  // once. A modal form is not a safe harbor: the command palette opens over
  // it and navigates through the same gate as a module tab (measured
  // live), so a dirty quick-add has to be registered or the route
  // changes under it without a question.
  useFormGuard(isDirty, t("labels:quickAdd.guardName", "The product form"));

  // A remembered pick the picker cannot offer does not seed the field — see
  // `useMissingPicks` for the two fields and why.
  useMissingPicks({
    storageOffered,
    categories: scopedCategories,
    formData,
    setFormData,
    remembered: heldFromMemory,
  });

  /**
   * Which fields the reader is looking at only because they filled in the
   * previous product. Derived rather than remembered: clearing either one
   * makes the notice go away by itself.
   */
  const carriedOver = {
    storage:
      Boolean(rememberedStorageId) &&
      formData.location_id === rememberedStorageId,
    category:
      Boolean(rememberedCategoryId) &&
      formData.category_id === rememberedCategoryId,
  };

  // One move, both ends: the fields empty for this product and the memory
  // empties for the ones after it — a clear that only emptied the fields
  // would re-arm itself from the store on the very next form.
  const clearCarriedOver = () => {
    clearLastUsed();
    setFormData((prev) => ({
      ...prev,
      ...(carriedOver.storage ? { location_id: "" } : {}),
      ...(carriedOver.category ? { category_id: "" } : {}),
    }));
  };

  /** Reads the photos into the form. Resolves true when the reading came
   * back with nothing in it — the camera tab says so in a sentence. */
  const handleVisionAI = async (files: File[]): Promise<boolean> => {
    if (files.length === 0) return false;
    setIsAnalyzing(true);
    try {
      const compressedFiles = await Promise.all(
        files.map((file) => compressImage(file)),
      );

      const visionData: VisionExtractResult = await visionApi.extract(
        compressedFiles,
        contextTag,
      );
      // A blurry or wrong photo is not an error: it answers 200 with every
      // field null. Merged, that marked an empty form as filled from a photo;
      // unremarked, it left the reader waiting on a reading that was over.
      if (!carriesValue(visionData)) return true;
      const nutrition = visionData.extra?.nutrition;
      // A resolver recognised the barcode the model read. Its name and brand
      // come from a catalogue entry rather than from a photograph, so they
      // win over the reading — but only over those two: the resolver knows
      // nothing about the carton in this person's hand, and its expiry date
      // (there is none) must not displace the one just read off it.
      const resolved = visionData.resolved;
      const resolvedMeta = (resolved?.metadata ?? {}) as {
        nutrition?: Record<string, unknown>;
        ingredients?: string;
        off_enriched?: boolean;
      };

      // Category matching — over the set the picker offers, not over the
      // catalogue: a suggestion the field cannot show is a suggestion the
      // save would drop on the floor.
      let matchedCategoryId = "";
      if (visionData.category) {
        const catName = visionData.category.toLowerCase();
        const matched = scopedCategories?.find(
          (c) =>
            c.name.toLowerCase() === catName ||
            (c.code &&
              String(tDyn(`categories:codes.${c.code}`)).toLowerCase() ===
                catName),
        );
        if (matched) {
          matchedCategoryId = matched.id;
        } else {
          toast(`${t("scan:aiSuggestion")}: "${visionData.category}"`, {
            duration: 4000,
            icon: "💡",
          });
        }
      }

      // Without a name, what counts as read is what lands in a form field; an
      // unresolved barcode or a production date has no field to show it in,
      // and an unmatched category has just said so in its own toast.
      const hasName = Boolean(resolved?.name || visionData.name);
      const filled = fieldsFilledByReading(
        visionData,
        resolvedMeta,
        nutrition,
        matchedCategoryId,
      );
      if (!hasName && filled.length === 0) return !visionData.category;

      // Update form data with vision results
      setFormData((prev) =>
        visionFormPatch(
          prev,
          visionData,
          resolved,
          resolvedMeta,
          nutrition,
          matchedCategoryId,
        ),
      );

      // The form is where the reading went, so it is where the reader goes —
      // a partial reading too, told what it filled in and what is missing.
      setActiveTab("manual");
      toast.success(readingSentence(hasName, filled, t));
      return false;
    } catch (error: unknown) {
      const msg = extractApiError(error, String(error));
      toast.error(t("errorAnalyzing", { ns: "scan", message: msg }));
      return false;
    } finally {
      setIsAnalyzing(false);
    }
  };

  return {
    activeTab,
    setActiveTab,
    visionEnabled,
    formData,
    setFormData,
    isDirty,
    errors,
    setErrors,
    fieldDefinitions,
    handleInputChange,
    handleMetadataChange,
    submit,
    templateUnit,
    pendingUnitChoice,
    resolveUnitChoice,
    isAnalyzing,
    imagePreview,
    setImagePreview,
    handleVisionAI,
    noStorages,
    hasHiddenStorages,
    carriedOver,
    clearCarriedOver,
    isStoragesError,
    refetchStorages,
    categories: scopedCategories,
    categoriesFailure,
    assignMutation,
    handleFileSelect,
    handleImageSelect,
  };
}

/**
 * Where this form would put the product if nobody chose anything.
 *
 * Spelled out apart from the seeding so that the form can tell a location
 * that was asked for from one that is merely left over from the last product
 * — the second is worth marking on screen, the first is not. `heldFromMemory`
 * is wider than that mark: a location scanned on an earlier visit is no choice
 * made in this form either, though nothing on screen calls it left over.
 */
function rememberedPicks(
  asked: Partial<ItemFormData> | undefined,
  initialStorageId: string | undefined,
  memory: Pick<
    ReturnType<typeof useScanStore.getState>,
    "storageContext" | "lastStorageId" | "lastCategoryId"
  >,
) {
  const rememberedStorageId =
    !asked?.location_id && !initialStorageId && !memory.storageContext?.id
      ? (memory.lastStorageId ?? "")
      : "";
  const rememberedCategoryId = !asked?.category_id
    ? (memory.lastCategoryId ?? "")
    : "";
  return {
    rememberedStorageId,
    rememberedCategoryId,
    heldFromMemory: {
      storageId: rememberedStorageId || memory.storageContext?.id || "",
      categoryId: rememberedCategoryId,
    },
  };
}

/** Whether a reading holds a value anywhere in it. Nested groups count by
 * their contents: with the nutrition module on, an empty reading still
 * carries `extra.nutrition`, as a group of nulls. */
function carriesValue(value: unknown): boolean {
  if (value === null || value === undefined || value === "") return false;
  if (typeof value === "object") return Object.values(value).some(carriesValue);
  return true;
}

type VisionReadField = "brand" | "expiry" | "weight" | "category" | "nutrition";

/** The form fields a reading puts a value in, besides the name, in the
 * order the sentence about them names them. */
function fieldsFilledByReading(
  visionData: VisionExtractResult,
  resolvedMeta: { nutrition?: Record<string, unknown>; ingredients?: string },
  nutrition: VisionNutritionFields | undefined,
  matchedCategoryId: string,
): VisionReadField[] {
  const filled: Array<VisionReadField | null> = [
    visionData.resolved?.brand || visionData.brand ? "brand" : null,
    visionData.expiry_date ? "expiry" : null,
    visionData.weight_value ? "weight" : null,
    matchedCategoryId ? "category" : null,
    resolvedMeta.nutrition ||
    resolvedMeta.ingredients ||
    carriesValue(nutrition)
      ? "nutrition"
      : null,
  ];
  return filled.filter((f) => f !== null);
}

/** What the toast says once a reading has gone into the form. */
function readingSentence(
  hasName: boolean,
  filled: VisionReadField[],
  t: TFunction,
): string {
  if (hasName) return t("scan:dataRecognized");
  const names: Record<VisionReadField, string> = {
    brand: t("labels:quickAdd.visionReadField.brand"),
    expiry: t("labels:quickAdd.visionReadField.expiry"),
    weight: t("labels:quickAdd.visionReadField.weight"),
    category: t("labels:quickAdd.visionReadField.category"),
    nutrition: t("labels:quickAdd.visionReadField.nutrition"),
  };
  const fields = filled.map((f) => names[f]).join(", ");
  return t("labels:quickAdd.visionReadPartly", { fields });
}

/** The form state a vision reading merges in.
 *
 * A resolver-recognised name and brand come from a catalogue entry rather
 * than from a photograph, so they win over the reading — but only over those
 * two: the resolver knows nothing about the carton in this person's hand, and
 * its expiry date (there is none) must not displace the one just read off it.
 */
function visionFormPatch(
  prev: ItemFormData,
  visionData: VisionExtractResult,
  resolved: VisionExtractResult["resolved"],
  resolvedMeta: {
    nutrition?: Record<string, unknown>;
    ingredients?: string;
    off_enriched?: boolean;
  },
  nutrition: VisionNutritionFields | undefined,
  matchedCategoryId: string,
): ItemFormData {
  return {
    ...prev,
    name: resolved?.name || visionData.name || prev.name,
    brand: resolved?.brand || visionData.brand || prev.brand,
    expiry_date: visionData.expiry_date || prev.expiry_date,
    category_id:
      visionData.category && matchedCategoryId
        ? matchedCategoryId
        : prev.category_id || "",
    weight: visionData.weight_value
      ? String(visionData.weight_value)
      : prev.weight,
    metadata: {
      ...prev.metadata,
      off_enriched: Boolean(resolvedMeta.off_enriched),
      nutrition_source: resolved ? "resolver" : "vision_capture",
      weight_value: visionData.weight_value,
      // The nutrition module contributes these to the same reading when
      // it is enabled; when it is not, the key is simply absent and what
      // was already on the form stays. A catalogue entry beats a reading
      // of a table in a photograph.
      nutrition:
        resolvedMeta.nutrition ??
        (nutrition
          ? { ...nutrition, ingredients: undefined }
          : prev.metadata?.nutrition),
      ingredients:
        resolvedMeta.ingredients ||
        nutrition?.ingredients ||
        prev.metadata?.ingredients,
    },
  };
}
