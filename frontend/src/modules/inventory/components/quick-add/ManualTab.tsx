import React from "react";
import { useTranslation } from "react-i18next";
import type { FieldDefinition, CategoryDTO } from "@/types";
import { useLocationsById } from "@/module-sdk";
import ProductFormContent from "../items/ProductFormContent";
import type { TemplateUnitPrompt } from "@/modules/inventory/hooks/useItemForm";
import { Slot } from "@/components/Slot";
import { Button } from "@/components/ui/Button";

interface ManualTabProps {
  formData: Record<string, unknown>;
  onChange: (key: string, value: unknown, isMetadata?: boolean) => void;
  onFileSelect?: (fieldKey: string, file: File) => void;
  onImageSelect?: (file: File) => void;
  errors: Record<string, string>;
  fieldDefinitions: FieldDefinition[];
  handleSubmit: (e: React.FormEvent) => void;
  isFromHistory?: boolean;
  categories?: CategoryDTO[];
  onAddCategory?: () => void;
  imagePreview?: string | null;
  setImagePreview?: (url: string | null) => void;
  /** Which fields are filled in from the previous product rather than from
   * anything the reader did on this screen. */
  carriedOver?: { storage: boolean; category: boolean };
  onClearCarriedOver?: () => void;
  /** The storage field's way out when the picker has nothing to offer. */
  storageGate?: React.ReactNode;
  /** Opens the caller's "new location" sheet from the storage picker. */
  onAddStorage?: (query: string) => void;
  /** The unit the matched product template keeps — the hint by the picker. */
  templateUnit?: TemplateUnitPrompt | null;
}

export function ManualTab({
  formData,
  onChange,
  onFileSelect,
  onImageSelect,
  errors,
  fieldDefinitions,
  handleSubmit,
  isFromHistory,
  categories,
  onAddCategory,
  imagePreview,
  setImagePreview,
  carriedOver,
  onClearCarriedOver,
  storageGate,
  onAddStorage,
  templateUnit,
}: ManualTabProps) {
  const { t } = useTranslation([
    "labels",
    "items",
    "common",
    "scan",
    "categories",
  ]);

  const { byId: chosenPlace } = useLocationsById([
    formData.location_id as string,
  ]);
  const storageTypeCode = chosenPlace.get(formData.location_id as string)
    ?.location_type?.type_code;

  const categoryContextTag = categories?.find(
    (c) => c.id === formData.category_id,
  )?.context_tag;

  return (
    <form id="quick-add-form" onSubmit={handleSubmit} className="space-y-6">
      {/* Two fields can be filled in without anybody on this screen having
          filled them in. Unmarked, that is indistinguishable from a choice —
          which is how tins of peas ended up filed under cold cuts. Saying
          where the values came from, and offering one move that takes them
          off, is the whole of it. */}
      {(carriedOver?.storage || carriedOver?.category) && (
        <div className="bg-surface-raised border border-border rounded-xl px-4 py-2.5 flex items-center justify-between gap-3">
          <p className="text-xs text-on-secondary">
            {carriedOver.storage && carriedOver.category
              ? t("items:carriedOver.both")
              : carriedOver.storage
                ? t("items:carriedOver.storage")
                : t("items:carriedOver.category")}
          </p>
          {onClearCarriedOver && (
            <Button
              size="content"
              type="button"
              variant="ghost"
              onClick={onClearCarriedOver}
              className="text-xs font-medium text-primary-600 hover:text-primary-700 shrink-0 min-h-11 md:min-h-0 min-w-11 md:min-w-0"
            >
              {t("common:actions.clear")}
            </Button>
          )}
        </div>
      )}

      {isFromHistory && (
        <div className="bg-primary-50 border border-primary-100 rounded-xl px-4 py-2.5 flex items-center gap-2 mb-2 animate-in fade-in slide-in-from-top-1 duration-300">
          <span className="text-lg">🧠</span>
          <div>
            <p className="text-xs font-medium text-primary-700 uppercase tracking-tight">
              {t("scan:dataFromHistory")}
            </p>
            <p className="text-[10px] text-primary-500 font-medium italic">
              {t("scan:historyHelp")}
            </p>
          </div>
        </div>
      )}

      {(() => {
        const meta = formData.metadata as Record<string, unknown> | undefined;
        const nutrition = meta?.nutrition as
          Record<string, unknown> | undefined;
        const hasNutritionData =
          Boolean(meta?.ingredients) ||
          Boolean(nutrition?.energy_kcal) ||
          Object.keys(nutrition || {}).length > 0;
        if (!hasNutritionData) return null;

        const source = meta?.nutrition_source as string | undefined;
        const isOff = meta?.off_enriched && source !== "vision_capture";

        if (isOff) {
          return (
            <div className="flex items-center justify-between px-1 py-1 mb-1 animate-in fade-in duration-500">
              <div className="flex items-center gap-1.5">
                <span className="text-xs opacity-70">🌍</span>
                <span className="text-[10px] font-medium text-on-muted uppercase tracking-tight">
                  {t("scan:dataFromOFFShort")}
                </span>
              </div>
              <a
                href={`https://world.openfoodfacts.org/product/${formData.barcode || ""}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[10px] text-primary-500 font-medium hover:underline uppercase"
              >
                {t("common:actions.source")} (ODbL) ↗
              </a>
            </div>
          );
        }

        if (source === "vision_capture") {
          return (
            <div className="flex items-center justify-between px-1 py-1 mb-1 animate-in fade-in duration-500">
              <div className="flex items-center gap-1.5">
                <span className="text-xs opacity-70">📷</span>
                <span className="text-[10px] font-medium text-on-muted uppercase tracking-tight">
                  {t("scan:dataFromVisionShort")}
                </span>
              </div>
              <span className="text-[10px] text-on-muted font-medium italic">
                {t("scan:visionDataHelp")}
              </span>
            </div>
          );
        }

        return null;
      })()}

      <ProductFormContent
        formData={formData}
        onChange={onChange}
        onFileSelect={onFileSelect}
        onImageSelect={onImageSelect}
        errors={errors}
        fieldDefinitions={fieldDefinitions}
        categories={categories}
        onAddCategory={onAddCategory}
        imagePreview={imagePreview}
        setImagePreview={setImagePreview}
        storageGate={storageGate}
        onAddStorage={onAddStorage}
        templateUnit={templateUnit}
      />

      {/* Product Info Display - Ingredients & Nutrition */}
      <Slot
        name="quick_add_product_info"
        data={{ formData, storageTypeCode, categoryContextTag }}
      />
    </form>
  );
}
