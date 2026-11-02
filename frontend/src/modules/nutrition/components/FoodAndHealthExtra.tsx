import { extractApiError } from "@/lib/errors";
import React, { useState } from "react";
import { makeTDynamic } from "@/lib/i18nHelpers";
import { Leaf, Camera, Check } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import NutritionScanner from "./NutritionScanner";
import { useUpdateNutrition } from "@/modules/nutrition/hooks/useNutrition";
import type { ProductTemplateNutritionInfo } from "@/lib/api/productTemplates";
import type { Item } from "@/types";
import { NutritionEmptyState } from "./NutritionEmptyState";
import { isFromOpenFoodFacts } from "../productNutrition";
import { NutritionEditForm } from "./NutritionEditForm";
import { NutritionValuesGrid } from "./NutritionValuesGrid";
import { productNutrition } from "../productNutrition";
import { Button } from "@/components/ui/Button";
import { useModules } from "@/contexts/ModulesContext";

interface FoodNutrition {
  nutrient_levels?: Record<string, string>;
}

interface FoodMetadata {
  nutriscore?: string;
  nutrition?: FoodNutrition;
  off_enriched?: boolean;
  ingredients?: string;
  source?: string;
  nutrient_levels?: Record<string, string>;
  nutrition_source?: string;
}

const FOOD_TYPE_CODES = new Set([
  "FREEZER",
  "FRIDGE",
  "PANTRY",
  "MEDICINE_CABINET",
]);

interface Props {
  data?: {
    item?: Item;
    formData?: Record<string, unknown>;
    storageType?: { type_code: string };
  };
}

const FoodAndHealthExtra: React.FC<Props> = ({ data }) => {
  const { t } = useTranslation(["nutrition", "common"]);
  const tDyn = makeTDynamic(t);
  const item = data?.item;
  const storageType = data?.storageType;
  const updateNutrition = useUpdateNutrition();
  const [showScanner, setShowScanner] = useState(false);
  const [showFullIngredients, setShowFullIngredients] = useState(false);
  const [showNutritionForm, setShowNutritionForm] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [nutritionForm, setNutritionForm] =
    useState<ProductTemplateNutritionInfo>({});

  // Reading a photo belongs to the vision module, which can be switched off.
  // Where it is off the camera is a dead end — the request behind it comes
  // back refused — so both entries hide (the same gate applied to
  // quick add).
  const { enabledModules } = useModules();
  const visionEnabled = enabledModules.includes("vision");

  if (!item) return null;

  // Only show for food/health storage types
  if (storageType && !FOOD_TYPE_CODES.has(storageType.type_code)) {
    return null;
  }

  const metadata = (item.metadata || {}) as FoodMetadata;
  let nutriScore: string | undefined = metadata.nutriscore?.toUpperCase();

  // Validate Nutri-Score (A-E only)
  if (nutriScore && !["A", "B", "C", "D", "E"].includes(nutriScore)) {
    nutriScore = undefined;
  }

  const ingredients = metadata.ingredients;
  const nutrition = metadata.nutrition || {};
  const nutrientLevels =
    nutrition.nutrient_levels || metadata.nutrient_levels || {};
  // The product's figures with the record's enrichment under them — a value
  // typed in below is saved to the product, so reading the record alone
  // answered every manual save with "No data".
  const values = productNutrition(item);
  const hasData = metadata.off_enriched || values || ingredients;

  const getLevelColor = (level: string) => {
    switch (level) {
      case "low":
        return "bg-accent-500";
      case "moderate":
        return "bg-yellow-500";
      case "high":
        return "bg-red-500";
      default:
        return "bg-gray-300";
    }
  };

  const getLevelLabel = (level: string, nutrient: string) => {
    return tDyn(`levels.${nutrient}.${level}`, {
      defaultValue: `${nutrient}: ${level}`,
    });
  };

  const getNutriColor = (score: string) => {
    switch (score) {
      case "A":
        return "bg-accent-600";
      case "B":
        return "bg-accent-400";
      case "C":
        return "bg-yellow-400";
      case "D":
        return "bg-orange-500";
      case "E":
        return "bg-red-600";
      default:
        return "bg-gray-400";
    }
  };

  const nutritionFields: Array<{
    key: keyof ProductTemplateNutritionInfo;
    label: string;
    unit: string;
  }> = [
    { key: "calories_kcal", label: String(t("energy")), unit: "kcal" },
    { key: "protein_g", label: String(t("proteins")), unit: "g" },
    { key: "fat_g", label: String(t("fat")), unit: "g" },
    { key: "carbs_g", label: String(t("carbohydrates")), unit: "g" },
    {
      key: "fiber_g",
      label: String(t("fiber", { defaultValue: "Fiber" })),
      unit: "g",
    },
    { key: "sugar_g", label: String(t("sugars")), unit: "g" },
    {
      key: "salt_g",
      label: String(t("salt")),
      unit: "g",
    },
  ];

  const handleOpenNutritionForm = () => {
    // The saved figures, so correcting one does not mean retyping the rest.
    setNutritionForm(values ?? {});
    setShowNutritionForm(true);
  };

  const handleSaveNutrition = async () => {
    if (!item?.template_id) return;
    setIsSaving(true);
    try {
      const payload: ProductTemplateNutritionInfo = Object.fromEntries(
        Object.entries(nutritionForm).filter(
          ([, v]) => v !== "" && v !== undefined && v !== null,
        ),
      ) as ProductTemplateNutritionInfo;
      await updateNutrition.mutateAsync({
        templateId: item.template_id,
        nutritionInfo: payload,
        itemId: item.id,
      });
      toast.success(t("nutritionForm.saved"));
      setShowNutritionForm(false);
    } catch (error) {
      toast.error(
        extractApiError(
          error,
          t("nutritionForm.saveError", {
            defaultValue: "Error saving nutrition",
          }),
        ),
      );
    } finally {
      setIsSaving(false);
    }
  };

  // The same form in both branches. It used to live only in the "there is
  // data" half, which made the empty state a closed loop: to type values in by
  // hand you first had to have values, so the one route out was a camera, a
  // legible label and an AI provider an admin had configured.
  const editForm = item.template_id ? (
    <NutritionEditForm
      nutritionFields={nutritionFields}
      nutritionForm={nutritionForm}
      showNutritionForm={showNutritionForm}
      isSaving={isSaving}
      onToggleForm={() =>
        showNutritionForm
          ? setShowNutritionForm(false)
          : handleOpenNutritionForm()
      }
      onFieldChange={(key, value) =>
        setNutritionForm((prev) => ({
          ...prev,
          [key]: value === "" ? undefined : Number(value),
        }))
      }
      onSave={handleSaveNutrition}
      t={t}
    />
  ) : null;

  if (!hasData) {
    return (
      <div className="space-y-2">
        <NutritionEmptyState
          item={item}
          showScanner={showScanner}
          onToggleScanner={() => setShowScanner(true)}
          onCloseScanner={() => setShowScanner(false)}
          hasManualEntry={editForm !== null}
          visionEnabled={visionEnabled}
          t={t}
        />
        {editForm}
      </div>
    );
  }

  return (
    <div className="space-y-4 pt-4 border-t border-border">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Leaf size={13} className="text-accent-600" />
          <span className="text-[10px] font-medium uppercase tracking-wider text-on-secondary">
            {t("title")}
          </span>
        </div>
        {visionEnabled && (
          <Button
            type="button"
            onClick={() => setShowScanner(true)}
            variant="outline"
            size="contentSm"
            className="px-2 py-1 gap-1 text-xs font-medium text-on-muted hover:bg-surface-card hover:border-primary-300 hover:text-primary-600 active:scale-95"
          >
            <Camera size={11} />
            {t("scanTable")}
          </Button>
        )}
      </div>

      <>
        <div className="flex flex-col sm:flex-row gap-4">
          {nutriScore && (
            <div className="flex-shrink-0">
              <p className="text-[10px] font-medium text-on-muted uppercase mb-1">
                {t("nutriScore")}
              </p>
              <div
                className={`w-10 h-10 ${getNutriColor(nutriScore)} text-white flex items-center justify-center rounded-xl font-semibold text-xl shadow-sm`}
              >
                {nutriScore}
              </div>
            </div>
          )}

          {Object.keys(nutrientLevels).length > 0 && (
            <div className="flex-1 min-w-0">
              <p className="text-[10px] font-medium text-on-muted uppercase mb-1">
                {t("nutrientLevels")}
              </p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(nutrientLevels).map(
                  ([nutrient, level]: [string, string]) => (
                    <div
                      key={nutrient}
                      className="flex items-center gap-1.5 px-2 py-1 bg-surface border rounded-lg"
                    >
                      <div
                        className={`w-2 h-2 rounded-full ${getLevelColor(level)}`}
                      />
                      <span className="text-[10px] font-medium text-on-secondary uppercase tracking-tight">
                        {getLevelLabel(level, nutrient)}
                      </span>
                    </div>
                  ),
                )}
              </div>
            </div>
          )}
        </div>

        {values && <NutritionValuesGrid values={values} />}

        {ingredients && (
          <div className="flex-1 min-w-0">
            <p className="text-[10px] font-medium text-on-muted uppercase mb-1">
              {t("ingredients")}
            </p>
            <p
              className={`text-xs text-on-secondary italic leading-relaxed transition-all duration-300 ${
                showFullIngredients ? "" : "line-clamp-3"
              }`}
            >
              {ingredients}
            </p>
            {ingredients.length > 150 && (
              <Button
                type="button"
                onClick={() => setShowFullIngredients(!showFullIngredients)}
                variant="link"
                size="contentSm"
                className="min-h-11 md:min-h-0 min-w-11 md:min-w-0 px-0 mt-1 text-[10px] font-medium uppercase"
              >
                {showFullIngredients
                  ? t("common:actions.lessOptions")
                  : t("common:actions.moreOptions")}
              </Button>
            )}
          </div>
        )}
      </>

      {/* Attribution */}
      {isFromOpenFoodFacts(metadata as Record<string, unknown>) ? (
        <div className="flex items-center gap-1.5 text-[10px]">
          <Leaf size={11} className="text-accent-600" />
          {/* The database's own name stays as it is written — a source is
              cited, not translated. The invitation to read about it is ours. */}
          <span className="text-accent-700 font-medium">Open Food Facts</span>
          <span className="text-on-muted">·</span>
          <a
            href="https://world.openfoodfacts.org"
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent-600 font-semibold hover:underline"
          >
            {t("source.learnMore")}
          </a>
          <span className="text-on-muted">·</span>
          <span className="text-on-muted">{t("source.communityNote")}</span>
        </div>
      ) : (
        metadata.nutrition_source === "vision_capture" && (
          <div className="flex items-center gap-1.5 text-[10px]">
            <Check size={11} className="text-accent-600" />
            <span className="text-accent-700 font-medium">
              {t("source.visionCapture")}
            </span>
          </div>
        )
      )}

      {/* Manual nutrition edit form */}
      {editForm}

      {visionEnabled && showScanner && (
        <NutritionScanner
          itemId={item.id}
          templateId={item.template_id ?? undefined}
          onClose={() => setShowScanner(false)}
          onSuccess={() => {}}
        />
      )}
    </div>
  );
};

export default FoodAndHealthExtra;
