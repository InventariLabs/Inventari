import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, Pencil, X } from "lucide-react";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { useUpdateMakerRecipe } from "@/modules/maker/hooks/useRecipes";
import { formatDecimalQty } from "@/utils/formatters";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import type { MakerRecipe } from "@/modules/maker/types/maker";

interface BatchYieldEditorProps {
  recipe: MakerRecipe;
}

// Lives outside CompositionTab so the tab's page-level function stays under
// its frozen function-size baseline; the yield read-out with its inline
// editor is a self-contained block and reaches for nothing the tab owns.
export function BatchYieldEditor({ recipe }: BatchYieldEditorProps) {
  const { t } = useTranslation("maker");
  const updateRecipe = useUpdateMakerRecipe();
  // null = not editing; otherwise the draft yield value.
  const [yieldDraft, setYieldDraft] = useState<string | null>(null);

  // The server names the unit: the BOM's own, or its product's when the BOM
  // stores none — looking up batch_yield_uom_id alone left the second case,
  // the common one, as a bare number.
  const yieldText = formatQuantityLocalized(
    t,
    recipe.batch_yield_qty,
    recipe.batch_yield_uom_symbol,
  );

  async function saveYield() {
    if (yieldDraft === null) return;
    const value = yieldDraft.trim();
    if (value === "" || Number.isNaN(Number(value)) || Number(value) <= 0) {
      // Closing the field on an invalid value looked exactly like a save: the
      // old number came back and nothing said why. Keep the field open and say it.
      toast.error(t("composition.errors.yieldInvalid"));
      return;
    }
    try {
      await updateRecipe.mutateAsync({
        recipeId: recipe.id,
        data: { batch_yield_qty: value },
      });
      setYieldDraft(null);
      toast.success(t("detail.yieldSaved"));
    } catch (err) {
      toast.error(extractApiError(err, t("detail.yieldSaveFailed")));
    }
  }

  return yieldDraft === null ? (
    <div className="flex flex-col items-end gap-1 shrink-0">
      <Button
        size="contentSm"
        variant="ghost"
        className="h-7 min-h-11 md:min-h-0 shrink-0"
        onClick={() => setYieldDraft(formatDecimalQty(recipe.batch_yield_qty))}
        aria-label={t("composition.batchYieldEdit")}
        data-testid="maker-yield-edit"
      >
        <span className="text-xs text-on-muted">
          {t("composition.batchYield", { qty: yieldText })}
        </span>
        <Pencil size={12} />
      </Button>
    </div>
  ) : (
    <div className="flex flex-col items-end gap-1 shrink-0">
      <div className="flex items-center gap-1.5">
        <span className="text-xs text-on-muted">
          {t("composition.batchYieldLabel")}
        </span>
        <Input
          wrapperClassName="w-20"
          type="number"
          step="any"
          min="0"
          value={yieldDraft}
          onChange={(e) => setYieldDraft(e.target.value)}
          className="h-8 text-sm"
          aria-label={t("composition.batchYieldLabel")}
          data-testid="maker-yield-input"
        />
        <Button
          size="sm"
          variant="ghost"
          onClick={saveYield}
          disabled={updateRecipe.isPending}
          aria-label={t("common:actions.save")}
          data-testid="maker-yield-save"
        >
          <Check size={16} className="text-accent-600" />
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setYieldDraft(null)}
          aria-label={t("common:actions.cancel")}
        >
          <X size={16} />
        </Button>
      </div>
      <p className="text-xs text-on-muted max-w-xs text-right">
        {t("composition.batchYieldHint")}
      </p>
    </div>
  );
}
