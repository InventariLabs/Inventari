import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { NutritionLabelScan } from "@/modules/recipes/pages/NutritionLabelScan";
import type { IngredientDefaultCreate } from "@/modules/recipes/types/nutrition-defaults";

type FormUpdater = React.SetStateAction<Partial<IngredientDefaultCreate>>;

interface NutritionAddFormProps {
  form: Partial<IngredientDefaultCreate>;
  isPending: boolean;
  /**
   * Whether reading a label off a photograph is available here.
   *
   * The reading is the vision module asking the nutrition module's questions,
   * behind the `vision:extract` permission — so where either module is off,
   * or the permission is not held, the button is not offered and the form is
   * the one it always was.
   */
  canScanLabel: boolean;
  onFormChange: (updater: FormUpdater) => void;
  onAdd: () => void;
  onCancel: () => void;
  t: (key: string, options?: Record<string, unknown>) => string;
}

export function NutritionAddForm({
  form,
  isPending,
  canScanLabel,
  onFormChange,
  onAdd,
  onCancel,
  t,
}: NutritionAddFormProps) {
  return (
    <div className="mb-4 p-4 rounded-xl border border-primary-200 bg-primary-50">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <h2 className="text-sm font-semibold text-on-secondary">
          {t("recipes:ingredient_defaults.add_title")}
        </h2>
        {canScanLabel && (
          <NutritionLabelScan
            // The reading fills the draft and stops there. What is typed
            // stays typed: only the values the label actually carried are
            // replaced, so a photograph that shows six of the seven does not
            // wipe the seventh.
            onRead={(values) => onFormChange((f) => ({ ...f, ...values }))}
            t={t}
          />
        )}
      </div>
      <div className="grid grid-cols-2 items-end sm:grid-cols-4 gap-3">
        <div className="col-span-2 sm:col-span-4">
          <Input
            label={t("recipes:ingredient_defaults.field_name")}
            value={form.name ?? ""}
            onChange={(e) =>
              onFormChange((f) => ({ ...f, name: e.target.value }))
            }
          />
        </div>
        {(
          [
            "calories_kcal",
            "protein_g",
            "fat_g",
            "carbs_g",
            "fiber_g",
            "sugar_g",
            "salt_g",
          ] as (keyof IngredientDefaultCreate)[]
        ).map((field) => (
          <Input
            key={field}
            type="number"
            min={0}
            step={0.01}
            label={t(`recipes:ingredient_defaults.nutrient_${field}`)}
            value={form[field] != null ? String(form[field]) : ""}
            onChange={(e) =>
              onFormChange((f) => ({
                ...f,
                [field]:
                  e.target.value === "" ? undefined : Number(e.target.value),
              }))
            }
          />
        ))}
      </div>
      <div className="flex gap-2 mt-3">
        <Button size="sm" onClick={onAdd} disabled={isPending}>
          {isPending ? <Loader2 size={16} className="animate-spin" /> : null}
          {t("recipes:ingredient_defaults.save")}
        </Button>
        <Button variant="ghost" size="sm" onClick={onCancel}>
          {t("common:actions.cancel")}
        </Button>
      </div>
    </div>
  );
}
