import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/Input";

interface Props {
  value: number | undefined;
  onChange: (value: number | undefined) => void;
  disabled?: boolean;
}

/**
 * The plan's default servings — the number every entry falls back to.
 *
 * Left empty, each entry follows the servings written on its own recipe, so a
 * recipe for one lands in a plan as one and the shopping list buys for one.
 */
export function DefaultServingsField({ value, onChange, disabled }: Props) {
  const { t } = useTranslation("recipes");

  return (
    <div>
      <Input
        type="number"
        min="1"
        step="1"
        label={t("meal_planner.default_servings")}
        value={value ?? ""}
        onChange={(e) => {
          const next = e.target.value.trim();
          onChange(next === "" ? undefined : Math.max(1, Number(next)));
        }}
        disabled={disabled}
        data-testid="meal-plan-default-servings"
      />
      <p className="mt-1 text-xs text-on-muted">
        {t("meal_planner.default_servings_hint")}
      </p>
    </div>
  );
}
