import { useTranslation } from "react-i18next";
import { Flame, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import type { RecipeNutrition } from "@/modules/recipes/types/nutrition";
import { formatNumberLocale } from "@/utils/formatters";

/** Below this share of ingredients with usable data a figure is partial. */
export const NUTRITION_COMPLETE_COVERAGE = 0.9;

interface Props {
  data: RecipeNutrition;
  servings: number;
  /** opens the recipe editor so missing per-ingredient data can be filled in. */
  onEditRecipe?: () => void;
}

function MacroBar({
  label,
  value,
  max,
  color,
}: {
  label: string;
  /** `null` is a nutrient nobody measured: no bar, and a dash, never 0 g. */
  value: number | null | undefined;
  max: number;
  color: string;
}) {
  const pct = value != null && max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-on-secondary w-14 shrink-0">{label}</span>
      <div className="flex-1 h-2 bg-surface-raised rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs font-medium text-on-secondary w-10 text-right tabular-nums">
        {value != null ? `${formatNumberLocale(value, 1)}g` : "–"}
      </span>
    </div>
  );
}

export default function NutritionCard({ data, servings, onEditRecipe }: Props) {
  const { t } = useTranslation("recipes");

  const n = data.per_serving;
  const maxMacro = Math.max(n.carbs_g ?? 0, n.fat_g ?? 0, n.protein_g ?? 0, 1);

  const microRows: { key: keyof typeof n; labelKey: string; color: string }[] =
    [
      { key: "fiber_g", labelKey: "nutrition.fiber", color: "bg-accent-400" },
      { key: "sugar_g", labelKey: "nutrition.sugar", color: "bg-amber-400" },
      { key: "salt_g", labelKey: "nutrition.salt", color: "bg-primary-400" },
    ];

  const hasAnyMicro = microRows.some((r) => (n[r.key] ?? 0) > 0);

  return (
    <Card className="p-0 shadow-sm">
      <div className="px-5 py-3 border-b border-border flex items-center justify-between">
        {/* No duplicate heading — the accordion header above owns the
            "Nutrition" title; keep only the per-serving hint here. */}
        <span className="text-xs text-on-muted">
          {t("nutrition.per_serving")}
        </span>
      </div>
      <div className="px-5 py-4 space-y-3">
        {/* Kcal hero */}
        <div className="flex items-center gap-2">
          <Flame size={18} className="text-amber-500 shrink-0" />
          <span className="text-2xl font-semibold text-on">
            {n.calories_kcal != null
              ? formatNumberLocale(n.calories_kcal, 0)
              : "–"}
          </span>
          <span className="text-sm text-on-secondary">kcal</span>
          {servings > 1 && n.calories_kcal != null && (
            <span className="ml-auto text-xs text-on-muted">
              {t("nutrition.total", {
                kcal: formatNumberLocale(n.calories_kcal * servings, 0),
              })}
            </span>
          )}
        </div>

        {/* Macro bars */}
        <div className="space-y-1.5">
          <MacroBar
            label={t("nutrition.carbs")}
            value={n.carbs_g}
            max={maxMacro}
            color="bg-amber-400"
          />
          <MacroBar
            label={t("nutrition.fat")}
            value={n.fat_g}
            max={maxMacro}
            color="bg-red-400"
          />
          <MacroBar
            label={t("nutrition.protein")}
            value={n.protein_g}
            max={maxMacro}
            color="bg-primary-400"
          />
        </div>

        {/* Micro rows: fiber, sugar, salt */}
        {hasAnyMicro && (
          <div className="space-y-1 pt-1 border-t border-border">
            {microRows.map(({ key, labelKey, color }) => (
              <MacroBar
                key={key}
                label={t(labelKey)}
                value={n[key]}
                max={maxMacro}
                color={color}
              />
            ))}
          </div>
        )}

        <p className="text-xs text-on-muted">
          {t(
            data.generic_values
              ? "nutrition.estimate_generic_note"
              : "nutrition.estimate_note",
          )}
        </p>

        {/* Coverage warning */}
        {data.coverage < NUTRITION_COMPLETE_COVERAGE && (
          <div className="flex flex-col items-start gap-2 pt-1 text-xs text-on-warning bg-amber-50 rounded-lg px-3 py-2">
            <div className="flex items-start gap-2">
              <AlertCircle size={13} className="mt-0.5 shrink-0" />
              <span>
                {t("nutrition.incomplete_warning", {
                  pct: Math.round(data.coverage * 100),
                })}
              </span>
            </div>
            {onEditRecipe && (
              <Button
                variant="ghost"
                size="contentSm"
                onClick={onEditRecipe}
                className="px-0 text-xs text-on-warning hover:text-on-warning min-h-11 md:min-h-0 min-w-11 md:min-w-0"
              >
                {t("common:form.edit")}
              </Button>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
