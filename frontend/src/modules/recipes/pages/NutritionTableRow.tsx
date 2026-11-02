import { Check, Loader2, Pencil, RotateCcw, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { NutritionBadge } from "@/modules/recipes/components/NutritionBadge";
import { formatNumberLocale } from "@/utils/formatters";
import type { IngredientDefault } from "@/modules/recipes/types/nutrition-defaults";

type EditDraft = {
  calories_kcal: string;
  protein_g: string;
  fat_g: string;
  carbs_g: string;
  fiber_g: string;
  sugar_g: string;
  salt_g: string;
};

interface NutritionTableRowProps {
  row: IngredientDefault;
  /** Whether this account may override the row — its controls are writes. */
  canWrite: boolean;
  isEditing: boolean;
  draft: EditDraft | null;
  isPending: boolean;
  onStartEdit: (row: IngredientDefault) => void;
  onCancelEdit: () => void;
  onSaveEdit: (row: IngredientDefault) => void;
  onResetOverride: (row: IngredientDefault) => void;
  onDraftChange: (field: keyof EditDraft, value: string) => void;
}

export function NutritionTableRow({
  row,
  canWrite,
  isEditing,
  draft,
  isPending,
  onStartEdit,
  onCancelEdit,
  onSaveEdit,
  onResetOverride,
  onDraftChange,
}: NutritionTableRowProps) {
  const { t } = useTranslation("recipes");

  const numInput = (field: keyof EditDraft, hidden?: string) => (
    <td className={`px-1 py-1 text-right${hidden ? ` ${hidden}` : ""}`}>
      <Input
        wrapperClassName="w-16"
        aria-label={String(field)}
        type="number"
        min={0}
        step={0.1}
        value={draft![field]}
        onChange={(e) => onDraftChange(field, e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onSaveEdit(row);
          if (e.key === "Escape") onCancelEdit();
        }}
        className="text-right text-xs border border-primary-300 rounded px-1 py-0.5 focus:outline-none focus:ring-1 focus:ring-primary-400"
      />
    </td>
  );

  return (
    <tr
      className={`transition-colors ${isEditing ? "bg-primary-50" : "hover:bg-surface"}`}
    >
      <td className="px-4 py-2.5 font-medium text-on">
        {row.name}
        {!row.is_system && (
          <span className="ml-1.5 text-xs text-primary-500 font-normal">
            <Pencil size={10} className="inline-block align-[-1px]" />
          </span>
        )}
      </td>

      {isEditing ? (
        <>
          {numInput("calories_kcal")}
          {numInput("protein_g", "hidden sm:table-cell")}
          {numInput("fat_g", "hidden md:table-cell")}
          {numInput("carbs_g", "hidden md:table-cell")}
          {numInput("fiber_g", "hidden lg:table-cell")}
          {numInput("sugar_g", "hidden lg:table-cell")}
          {numInput("salt_g", "hidden lg:table-cell")}
        </>
      ) : (
        <>
          <td className="px-3 py-2.5 text-right">
            <span className="text-sm font-semibold text-on tabular-nums">
              {formatNumberLocale(row.calories_kcal, 0)}
            </span>
          </td>
          <td className="px-3 py-2.5 text-right hidden sm:table-cell">
            <NutritionBadge value={row.protein_g} unit="g" />
          </td>
          <td className="px-3 py-2.5 text-right hidden md:table-cell">
            <NutritionBadge value={row.fat_g} unit="g" />
          </td>
          <td className="px-3 py-2.5 text-right hidden md:table-cell">
            <NutritionBadge value={row.carbs_g} unit="g" />
          </td>
          <td className="px-3 py-2.5 text-right hidden lg:table-cell">
            <NutritionBadge value={row.fiber_g} unit="g" />
          </td>
          <td className="px-3 py-2.5 text-right hidden lg:table-cell">
            <NutritionBadge value={row.sugar_g} unit="g" />
          </td>
          <td className="px-3 py-2.5 text-right hidden lg:table-cell">
            <NutritionBadge value={row.salt_g} unit="g" />
          </td>
        </>
      )}

      <td className="px-3 py-2.5">
        {/* "System" is the rule for this table, not the exception — a badge on
            all 85 rows carries no information, so only the rows an
            organization has overridden are badged. The column is headed after
            what it marks; headed "Source" it promised something every row
            withheld. */}
        {!row.is_system && (
          <Badge variant="info" className="text-xs">
            {t("ingredient_defaults.custom")}
          </Badge>
        )}
      </td>

      <td className="px-2 py-2.5">
        {canWrite && (
          <div className="flex items-center gap-0.5 justify-end">
            {isEditing ? (
              <>
                <Button
                  type="button"
                  size="iconSm"
                  variant="ghost"
                  onClick={() => onSaveEdit(row)}
                  disabled={isPending}
                  className="rounded text-primary-500 hover:text-primary-700 hover:bg-transparent active:bg-transparent"
                  aria-label={t("common:actions.save")}
                  title={t("common:actions.save")}
                >
                  {isPending ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <Check size={16} />
                  )}
                </Button>
                <Button
                  type="button"
                  size="iconSm"
                  variant="ghost"
                  onClick={onCancelEdit}
                  className="rounded text-on-muted hover:text-on-secondary hover:bg-transparent active:bg-transparent"
                  aria-label={t("common:actions.cancel")}
                  title={t("common:actions.cancel")}
                >
                  <X size={16} />
                </Button>
              </>
            ) : (
              <>
                <Button
                  type="button"
                  size="iconSm"
                  variant="ghost"
                  onClick={() => onStartEdit(row)}
                  className="rounded text-on-muted hover:text-primary-500 hover:bg-transparent active:bg-transparent"
                  aria-label={t("ingredient_defaults.tooltip_edit")}
                  title={t("ingredient_defaults.tooltip_edit")}
                >
                  <Pencil size={16} />
                </Button>
                {!row.is_system && (
                  <Button
                    type="button"
                    size="iconSm"
                    variant="ghost"
                    onClick={() => onResetOverride(row)}
                    className="rounded text-on-muted hover:text-amber-500 hover:bg-transparent active:bg-transparent"
                    aria-label={t("ingredient_defaults.tooltip_reset")}
                    title={t("ingredient_defaults.tooltip_reset")}
                  >
                    <RotateCcw size={16} />
                  </Button>
                )}
              </>
            )}
          </div>
        )}
      </td>
    </tr>
  );
}
