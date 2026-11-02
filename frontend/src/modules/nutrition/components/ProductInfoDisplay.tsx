import React, { useState } from "react";
import { Leaf, ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { formatQuantityLocale } from "@/utils/formatters";
import { FOOD_CONTEXTS } from "@/config/systemFields";
import CommunityDataNote from "./CommunityDataNote";

const FOOD_TYPE_CODES = new Set([
  "FREEZER",
  "FRIDGE",
  "PANTRY",
  "MEDICINE_CABINET",
]);

interface Props {
  data?: {
    formData?: Record<string, unknown>;
    storageTypeCode?: string;
    categoryContextTag?: string | null;
  };
}

const ProductInfoDisplay: React.FC<Props> = ({ data }) => {
  const { formData = {}, storageTypeCode, categoryContextTag } = data || {};
  const { t } = useTranslation(["nutrition", "common"]);
  const [showFullIngredients, setShowFullIngredients] = useState(false);

  const metadata = (formData.metadata || {}) as Record<string, unknown>;
  const ingredients = metadata.ingredients as string | undefined;
  const nutrition = (metadata.nutrition || {}) as Record<string, unknown>;
  const hasNutritionValues =
    nutrition.energy_kcal != null ||
    Object.values(nutrition).some(
      (v) => v !== undefined && v !== null && v !== "",
    );
  const hasFoodData = Boolean(ingredients) || hasNutritionValues;

  // Don't render for non-food storage types (unless already has food data from migration)
  if (storageTypeCode && !FOOD_TYPE_CODES.has(storageTypeCode)) {
    return null;
  }

  // A category of another vertical (equipment) says this is not food, whatever
  // the scan found.
  if (categoryContextTag && !FOOD_CONTEXTS.includes(categoryContextTag)) {
    return null;
  }

  // Don't render if no enriched food data
  if (!hasFoodData) {
    return null;
  }

  const formatVal = (val: unknown) => {
    if (val === undefined || val === null || val === "") return "-";
    const num = typeof val === "string" ? parseFloat(val) : (val as number);
    if (isNaN(num)) return "-";
    // At most one decimal, no padding — the shape the browser's locale used
    // to print, now in the interface's own language.
    return formatQuantityLocale(String(num), 1);
  };

  return (
    <div className="pt-4 border-t border-border space-y-4 animate-in fade-in duration-300">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Leaf size={14} className="text-accent-600" />
        <h4 className="text-[10px] font-medium uppercase tracking-widest text-on-muted">
          {t("title")}
        </h4>
      </div>

      {/* Nutrition Facts Grid */}
      {hasFoodData && hasNutritionValues && (
        <div className="grid grid-cols-3 gap-2">
          {[
            {
              label: t("energy"),
              value: nutrition.energy_kcal,
              unit: "kcal",
            },
            {
              label: t("proteins"),
              value: nutrition.proteins,
              unit: "g",
            },
            {
              label: t("fat"),
              value: nutrition.fat,
              unit: "g",
            },
            {
              label: t("carbohydrates"),
              value: nutrition.carbohydrates,
              unit: "g",
            },
            { label: t("sugars"), value: nutrition.sugars, unit: "g" },
            { label: t("fiber"), value: nutrition.fiber, unit: "g" },
            { label: t("salt"), value: nutrition.salt, unit: "g" },
          ].map((n) => (
            <div
              key={n.label}
              className="bg-surface border rounded-lg p-2 text-center text-[10px]"
            >
              <p className="font-medium text-on-muted uppercase leading-tight mb-0.5">
                {n.label}
              </p>
              <p className="font-medium text-on-secondary text-xs">
                {formatVal(n.value)}
              </p>
              <p className="text-[10px] text-on-muted">{n.unit}</p>
            </div>
          ))}
        </div>
      )}
      {hasNutritionValues && <CommunityDataNote metadata={metadata} />}

      {/* Ingredients */}
      {hasFoodData && ingredients && (
        <div>
          <p className="text-[10px] font-medium text-on-muted uppercase mb-2">
            {t("ingredients")}
          </p>
          <p
            className={`text-xs text-on-secondary leading-relaxed transition-all duration-300 ${
              showFullIngredients ? "" : "line-clamp-3"
            }`}
          >
            {ingredients}
          </p>
          {ingredients.length > 150 && (
            <Button
              size="content"
              type="button"
              variant="link"
              onClick={() => setShowFullIngredients(!showFullIngredients)}
              className="min-h-11 md:min-h-0 min-w-11 md:min-w-0 justify-start text-[10px] font-medium text-primary-600 uppercase mt-1.5 gap-1"
            >
              {showFullIngredients ? (
                <>{t("common:actions.lessOptions", { defaultValue: "Less" })}</>
              ) : (
                <>
                  {t("common:actions.moreOptions", { defaultValue: "More" })}
                  <ChevronDown size={10} />
                </>
              )}
            </Button>
          )}
        </div>
      )}
    </div>
  );
};

export default ProductInfoDisplay;
