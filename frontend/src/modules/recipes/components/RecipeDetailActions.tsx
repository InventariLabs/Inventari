import { useState } from "react";
import { extractApiError } from "@/lib/errors";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { copyTextOrExplain } from "@/lib/clipboard";
import {
  CalendarPlus,
  CheckCircle2,
  ChefHat,
  Copy,
  Download,
  Edit2,
  Factory,
  FileJson,
  PackageOpen,
  Printer,
  Star,
  Trash2,
} from "lucide-react";
import { ActionMenu } from "@/components/ui/ActionMenu";
import { Button } from "@/components/ui/Button";
import { useModules } from "@/contexts/ModulesContext";
import { downloadBlob } from "@/utils/helpers";
import { TypedSlot } from "@/module-sdk";
import { CookForStockButton } from "./CookForStockButton";
import {
  AddToMealPlanButton,
  MealPlanPickerModal,
} from "./MealPlanPickerModal";
import { useExportRecipe } from "../hooks/useRecipes";
import type { Recipe } from "../types/core";

interface RecipeDetailActionsProps {
  recipe: Recipe;
  justCompleted: boolean;
  hasInstructions: boolean;
  onToggleFavorite: () => void;
  onDuplicate: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onStartPicking: () => void;
  onStartCooking: () => void;
  /** Whether the account may change the recipe (`recipes:write`). */
  canWrite?: boolean;
  /**
   * Whether it may finish a picking or cooking session (`recipes:consume`).
   *
   * Separate from the first: starting a session is an ordinary write, but
   * the endpoint that takes the stock off the shelf asks for its own key.
   * Offering the session to an account that cannot finish it is the same
   * defect one step later — the refusal would arrive at the last screen.
   */
  canConsume?: boolean;
}

/**
 * Header actions of the recipe detail page (rendered by the shell via
 * useModulePageHeader). hierarchy:
 *
 * - "Cook step by step" is the primary action — the reason a recipe is open.
 *   It reads the recipe and touches no shelf by itself; its final screen asks
 *   whether the ingredients come off the stock.
 * - "Take from stock" is secondary — it moves stock right now, and the name
 *   says so before anyone clicks.
 * - Delete, Duplicate and Print sit behind an overflow menu on every screen
 *   size — the destructive action is no longer one misclick away from Edit.
 * - The two production/planning actions stay grouped, each describing its
 *   consequence via a native tooltip.
 */
export function RecipeDetailActions({
  recipe,
  justCompleted,
  hasInstructions,
  onToggleFavorite,
  onDuplicate,
  onEdit,
  onDelete,
  onStartPicking,
  onStartCooking,
  canWrite = true,
  canConsume = true,
}: RecipeDetailActionsProps) {
  const { t } = useTranslation(["recipes", "common"]);
  const { isModuleEnabled } = useModules();
  const cookForStock = isModuleEnabled("maker");
  // The phone's two entries live in the ⋯ menu, but their sheets live here:
  // a sheet rendered inside the menu is laid out against the menu, and
  // closing the menu would unmount it.
  const [sheet, setSheet] = useState<"cook" | "plan" | null>(null);

  return (
    <div className="flex items-center gap-1 flex-wrap justify-end">
      {canWrite && (
        <Button
          variant="ghost"
          size="icon"
          onClick={onToggleFavorite}
          aria-label={t("common:a11y.favorite")}
          title={t("common:a11y.favorite")}
          className="text-on-muted hover:text-on-warning hover:bg-amber-50"
        >
          {recipe.is_favorite ? (
            <Star size={16} className="text-amber-500 fill-amber-500" />
          ) : (
            <Star size={16} />
          )}
        </Button>
      )}
      {canWrite && (
        <Button
          variant="ghost"
          size="icon"
          onClick={onEdit}
          aria-label={t("common:a11y.edit")}
          title={t("common:a11y.edit")}
          className="text-on-muted hover:text-on hover:bg-primary-50"
        >
          <Edit2 size={16} />
        </Button>
      )}

      <OverflowMenu
        recipe={recipe}
        onDuplicate={onDuplicate}
        onDelete={onDelete}
        canWrite={canWrite}
        onCookForStock={cookForStock ? () => setSheet("cook") : undefined}
        onAddToMealPlan={() => setSheet("plan")}
      />
      {canWrite && cookForStock && (
        <TypedSlot
          name="recipe_cook_for_stock"
          data={{
            open: sheet === "cook",
            onClose: () => setSheet(null),
            recipe,
          }}
        />
      )}
      {canWrite && (
        <MealPlanPickerModal
          open={sheet === "plan"}
          onClose={() => setSheet(null)}
          recipe={recipe}
        />
      )}

      {/* Production/planning pair — grouped; each action names its effect.
 Below sm they live in the overflow menu instead. */}
      {canWrite && (
        <div className="hidden sm:flex items-center gap-1 border border-border rounded-lg px-1 py-0.5 bg-surface-card/60">
          <span title={t("recipes:actions.cook_for_stock_hint")}>
            <CookForStockButton recipe={recipe} />
          </span>
          <span title={t("recipes:actions.add_to_meal_plan_hint")}>
            <AddToMealPlanButton recipe={recipe} />
          </span>
        </div>
      )}

      {/* Secondary: pulls ingredients from stock right now — the one of the
          pair whose name owns up to it */}
      {canWrite && canConsume && (
        <Button
          variant="secondary"
          onClick={onStartPicking}
          disabled={justCompleted}
          className="gap-2"
        >
          {justCompleted ? (
            <>
              <CheckCircle2 size={16} />
              {t("picking.just_completed")}
            </>
          ) : (
            <>
              <PackageOpen size={16} />
              {t("actions.start_picking")}
            </>
          )}
        </Button>
      )}

      {/* Primary: cook step by step */}
      {hasInstructions && canWrite && canConsume && (
        <Button onClick={onStartCooking} className="gap-2">
          <ChefHat size={16} />
          {t("cooking_mode.start_cooking")}
        </Button>
      )}
    </div>
  );
}

/**
 * Overflow "⋯" menu: Delete, Duplicate, Print and the two export actions on
 * every screen size; the production/planning pair joins it below `sm`.
 */
function OverflowMenu({
  recipe,
  onDuplicate,
  onDelete,
  canWrite,
  onCookForStock,
  onAddToMealPlan,
}: {
  recipe: Recipe;
  onDuplicate: () => void;
  onDelete: () => void;
  /** Print and the two exports are reads and stay; the rest are writes. */
  canWrite: boolean;
  /** Absent when the maker module is off — the entry is not offered. */
  onCookForStock?: () => void;
  onAddToMealPlan: () => void;
}) {
  const { t } = useTranslation(["recipes", "common"]);
  const exportMutation = useExportRecipe();

  const handleExportJson = async () => {
    try {
      const data = await exportMutation.mutateAsync({
        id: recipe.id,
        format: "json",
      });
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      downloadBlob(blob, `recipe-${recipe.id}.json`);
    } catch (error) {
      toast.error(extractApiError(error, t("recipes:errors.save_failed")));
    }
  };

  const handleExportSchemaOrg = async () => {
    try {
      const data = await exportMutation.mutateAsync({
        id: recipe.id,
        format: "schema_org",
      });
      const copied = await copyTextOrExplain(
        JSON.stringify(data, null, 2),
        t("common:copy.failed"),
      );
      if (copied) toast.success(t("recipes:import_export.export_copied"));
    } catch (error) {
      toast.error(extractApiError(error, t("recipes:errors.save_failed")));
    }
  };

  return (
    <ActionMenu
      label={t("recipes:meal_planner.more_actions")}
      triggerClassName="hover:bg-primary-50"
      actions={[
        // From `sm` up these two have buttons of their own in the header.
        ...(canWrite && onCookForStock
          ? [
              {
                id: "cook-for-stock",
                label: t("recipes:cookForStock.button"),
                icon: <Factory size={16} />,
                className: "sm:hidden",
                onSelect: onCookForStock,
              },
            ]
          : []),
        ...(canWrite
          ? [
              {
                id: "add-to-meal-plan",
                label: t("recipes:meal_planner.add_to_plan"),
                icon: <CalendarPlus size={16} />,
                className: "sm:hidden",
                onSelect: onAddToMealPlan,
              },
            ]
          : []),
        ...(canWrite
          ? [
              {
                id: "duplicate",
                label: t("recipes:actions.duplicate"),
                icon: <Copy size={16} />,
                onSelect: onDuplicate,
              },
            ]
          : []),
        {
          id: "print",
          label: t("recipes:print.print"),
          icon: <Printer size={16} />,
          onSelect: () => window.print(),
        },
        {
          id: "export-json",
          label: t("recipes:import_export.export_json"),
          icon: <Download size={16} />,
          disabled: exportMutation.isPending,
          onSelect: () => void handleExportJson(),
        },
        {
          id: "export-schema-org",
          label: t("recipes:import_export.export_schema_org"),
          icon: <FileJson size={16} />,
          disabled: exportMutation.isPending,
          onSelect: () => void handleExportSchemaOrg(),
        },
        ...(canWrite
          ? [
              {
                id: "delete",
                label: t("common:a11y.delete"),
                icon: <Trash2 size={16} />,
                destructive: true,
                onSelect: onDelete,
              },
            ]
          : []),
      ]}
    />
  );
}
