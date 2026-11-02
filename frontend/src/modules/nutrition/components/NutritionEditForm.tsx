import { ChevronDown, ChevronUp, Pencil, Save } from "lucide-react";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import type { ProductTemplateNutritionInfo } from "@/lib/api/productTemplates";

interface NutritionFieldsProps {
  nutritionFields: Array<{
    key: keyof ProductTemplateNutritionInfo;
    label: string;
    unit: string;
  }>;
  nutritionForm: ProductTemplateNutritionInfo;
  showNutritionForm: boolean;
  isSaving: boolean;
  onToggleForm: () => void;
  onFieldChange: (
    key: keyof ProductTemplateNutritionInfo,
    value: string,
  ) => void;
  onSave: () => void;
  t: (key: string, options?: Record<string, unknown>) => string;
}

export function NutritionEditForm({
  nutritionFields,
  nutritionForm,
  showNutritionForm,
  isSaving,
  onToggleForm,
  onFieldChange,
  onSave,
  t,
}: NutritionFieldsProps) {
  return (
    <div className="border border-border rounded-xl overflow-hidden">
      <Button
        type="button"
        onClick={onToggleForm}
        variant="ghost"
        size="contentSm"
        className="w-full px-3 py-2.5 justify-between bg-surface text-xs font-medium text-on-secondary"
      >
        <span className="flex items-center gap-1.5">
          <Pencil size={11} />
          {t("nutrition:nutritionForm.title", {
            defaultValue: "Edit nutrition values",
          })}
        </span>
        {showNutritionForm ? (
          <ChevronUp size={13} />
        ) : (
          <ChevronDown size={13} />
        )}
      </Button>

      {showNutritionForm && (
        <div className="p-3 space-y-3">
          <p className="text-[10px] text-on-muted">
            {t("nutrition:nutritionForm.hint", {
              defaultValue: "Values per 100g / 100ml",
            })}
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {nutritionFields.map((field) => (
              <div key={field.key}>
                <Input
                  // The unit belongs in the name a screen reader reads out:
                  // "Fat (g)" is the question, "Fat" alone is half of it.
                  label={`${field.label} (${field.unit})`}
                  type="number"
                  min={0}
                  step="0.1"
                  value={nutritionForm[field.key] ?? ""}
                  onChange={(e) => onFieldChange(field.key, e.target.value)}
                  className="w-full rounded-lg border border-border px-2 py-1.5 text-xs text-on focus:border-primary-400 focus:outline-none"
                />
              </div>
            ))}
          </div>
          <Button
            type="button"
            disabled={isSaving}
            onClick={onSave}
            variant="default"
            size="contentSm"
            className="px-3 py-1.5 text-xs font-medium shadow-none"
          >
            <Save size={12} />
            {isSaving
              ? t("common:actions.saving", { defaultValue: "Saving…" })
              : t("common:actions.save")}
          </Button>
        </div>
      )}
    </div>
  );
}
