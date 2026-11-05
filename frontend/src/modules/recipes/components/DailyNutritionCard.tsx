import { format, parseISO } from "date-fns";
import { useTranslation } from "react-i18next";
import { Card } from "@/components/ui/Card";
import type { MealPlan } from "@/modules/recipes/types/mealplans";
import { dateFnsLocale } from "@/utils/formatters";

interface Props {
  days: MealPlan["daily_nutrition_summary"];
}

/**
 * Per-day macro totals of a plan, one serving of each planned meal; a day built from partly measured recipes says so.
 * Unlike a recipe's own card there is no "complete enough" threshold: a day sums
 * several dishes, so 90% of its ingredients can still leave a whole dish out.
 */
export function DailyNutritionCard({ days }: Props) {
  const { t } = useTranslation("recipes");
  if (days.length === 0) return null;
  const anyGeneric = days.some((d) => d.generic_values);
  return (
    <Card className="p-0 overflow-hidden shadow-sm">
      <div className="px-5 py-3 border-b border-border">
        <h2 className="text-sm font-semibold text-on-secondary">
          {t("meal_planner.daily_nutrition")}
        </h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-on-muted border-b border-border">
              <th className="text-left font-medium px-3 sm:px-5 py-2">
                {t("meal_planner.date")}
              </th>
              <th className="text-right font-medium px-2 sm:px-3 py-2 whitespace-nowrap">
                {t("nutrition.carbs")}
              </th>
              <th className="text-right font-medium px-2 sm:px-3 py-2 whitespace-nowrap">
                {t("nutrition.protein")}
              </th>
              <th className="text-right font-medium px-2 sm:px-3 py-2 whitespace-nowrap">
                {t("nutrition.fat")}
              </th>
              <th className="text-right font-medium px-3 sm:px-5 py-2 whitespace-nowrap">
                {t("nutrition.calories")}
              </th>
            </tr>
          </thead>
          {days.map((day) => (
            <tbody
              key={day.date}
              className="border-b border-border/50 last:border-0"
            >
              <tr>
                <td className="px-3 sm:px-5 py-2 text-on-secondary whitespace-nowrap">
                  {format(parseISO(day.date), "EEE d MMM", {
                    locale: dateFnsLocale(),
                  })}
                </td>
                <td className="px-2 sm:px-3 py-2 text-right tabular-nums whitespace-nowrap text-on-secondary">
                  {day.carbs_g != null ? `${day.carbs_g} g` : "–"}
                </td>
                <td className="px-2 sm:px-3 py-2 text-right tabular-nums whitespace-nowrap text-on-secondary">
                  {day.protein_g != null ? `${day.protein_g} g` : "–"}
                </td>
                <td className="px-2 sm:px-3 py-2 text-right tabular-nums whitespace-nowrap text-on-secondary">
                  {day.fat_g != null ? `${day.fat_g} g` : "–"}
                </td>
                <td className="px-3 sm:px-5 py-2 text-right tabular-nums whitespace-nowrap font-medium text-on">
                  {day.calories_kcal != null
                    ? `${day.calories_kcal} kcal`
                    : "–"}
                </td>
              </tr>
              {day.coverage < 1 && (
                <tr>
                  <td
                    colSpan={5}
                    className="px-3 sm:px-5 pb-2 -mt-1 text-xs text-on-muted"
                  >
                    {t("nutrition.incomplete_warning", {
                      pct: Math.round(day.coverage * 100),
                    })}
                  </td>
                </tr>
              )}
            </tbody>
          ))}
        </table>
      </div>
      <p className="px-5 py-3 text-xs text-on-muted border-t border-border">
        {anyGeneric
          ? t("nutrition.daily_estimate_generic_note")
          : t("nutrition.daily_estimate_note")}
      </p>
    </Card>
  );
}
