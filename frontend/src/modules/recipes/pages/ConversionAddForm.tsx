import { X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import type { UnitConversionCreate } from "@/modules/recipes/types/nutrition-defaults";

const CATEGORY_ORDER = ["dry", "liquid", "fat", "other"] as const;

interface ConversionAddFormProps {
  form: Partial<UnitConversionCreate>;
  onFormChange: React.Dispatch<
    React.SetStateAction<Partial<UnitConversionCreate>>
  >;
  onAdd: () => void;
  onCancel: () => void;
  t: (key: string) => string;
}

export function categoryLabel(t: (k: string) => string, cat: string) {
  const key = `unit_conversions.category_${cat}`;
  const label = t(key);
  return label === key ? cat : label;
}

export function ConversionAddForm({
  form,
  onFormChange,
  onAdd,
  onCancel,
  t,
}: ConversionAddFormProps) {
  return (
    <div className="bg-surface-raised rounded-lg border border-border p-4 space-y-3">
      <div className="grid grid-cols-2 items-end gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Input
          label={t("recipes:unit_conversions.field_key")}
          value={form.ingredient_key || ""}
          onChange={(e) =>
            onFormChange((f) => ({ ...f, ingredient_key: e.target.value }))
          }
        />
        <Input
          label={t("recipes:unit_conversions.field_name")}
          value={form.ingredient_name || ""}
          onChange={(e) =>
            onFormChange((f) => ({ ...f, ingredient_name: e.target.value }))
          }
        />
        <Input
          label={t("recipes:unit_conversions.field_unit")}
          value={form.source_unit || ""}
          onChange={(e) =>
            onFormChange((f) => ({ ...f, source_unit: e.target.value }))
          }
        />
        <Input
          type="number"
          label={t("recipes:unit_conversions.field_metric_qty")}
          value={form.metric_quantity ?? ""}
          onChange={(e) =>
            onFormChange((f) => ({
              ...f,
              metric_quantity: Number(e.target.value),
            }))
          }
        />
        <NativeSelect
          label={t("recipes:unit_conversions.field_metric_unit")}
          value={form.metric_unit || "g"}
          onChange={(e) =>
            onFormChange((f) => ({ ...f, metric_unit: e.target.value }))
          }
        >
          <option value="g">g</option>
          <option value="ml">ml</option>
        </NativeSelect>
        <NativeSelect
          label={t("recipes:unit_conversions.field_category")}
          value={form.category || "dry"}
          onChange={(e) =>
            onFormChange((f) => ({ ...f, category: e.target.value }))
          }
        >
          {CATEGORY_ORDER.map((c) => (
            <option key={c} value={c}>
              {categoryLabel(t, c)}
            </option>
          ))}
        </NativeSelect>
      </div>
      <div className="flex gap-2">
        <Button size="sm" onClick={onAdd}>
          {t("recipes:unit_conversions.add")}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={onCancel}
          aria-label={t("common:actions.cancel")}
          title={t("common:actions.cancel")}
        >
          <X size={16} />
        </Button>
      </div>
    </div>
  );
}
