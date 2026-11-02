import { useTranslation } from "react-i18next";
import type { ProductTemplateNutritionInfo } from "@/lib/api/productTemplates";
import { formatQuantityLocale } from "@/utils/formatters";
import { NUTRIENT_FIELDS, type NutrientKey } from "../productNutrition";

/** The figures a product carries per 100 g, one tile each; a figure it lacks gets no tile. */
export function NutritionValuesGrid({
  values,
}: {
  values: ProductTemplateNutritionInfo;
}) {
  const { t } = useTranslation("nutrition");
  const labels: Record<NutrientKey, string> = {
    calories_kcal: t("energy"),
    protein_g: t("proteins"),
    fat_g: t("fat"),
    carbs_g: t("carbohydrates"),
    fiber_g: t("fiber"),
    sugar_g: t("sugars"),
    salt_g: t("salt"),
  };
  const present = NUTRIENT_FIELDS.filter(({ key }) => values[key] != null);

  return (
    <dl className="grid grid-cols-3 sm:grid-cols-6 gap-2">
      {present.map(({ key, unit }) => (
        <div
          key={key}
          className="bg-surface-card border rounded-lg p-2 text-center shadow-sm"
        >
          <dt className="text-[10px] font-medium text-on-muted uppercase leading-tight mb-0.5">
            {labels[key]}
          </dt>
          <dd className="text-xs font-medium text-on-secondary">
            {/* At most one decimal, no padding, in the interface's language. */}
            {formatQuantityLocale(String(values[key]), 1)}
            <span className="block text-[10px] text-on-muted">{unit}</span>
          </dd>
        </div>
      ))}
    </dl>
  );
}
