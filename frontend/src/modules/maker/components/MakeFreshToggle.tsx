import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Checkbox } from "@/module-sdk";
import { extractApiError } from "@/lib/errors";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { useUpdateBomLine } from "@/modules/maker/hooks/useRecipes";
import type { BomLine } from "@/modules/maker/types/maker";

/**
 * What an ingredient that has a recipe of its own does in a run: the part its
 * stock covers is taken from the shelf, the rest is made through the recipe —
 * unless the line says it is made fresh every time. Shown beside the line in
 * the formula tree, where the recipe below it is visible.
 */
export function MakeFreshToggle({
  line,
  canManage,
}: {
  line: BomLine;
  canManage: boolean;
}) {
  const { t } = useTranslation("maker");
  const update = useUpdateBomLine();

  return (
    <span className="ml-auto flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-on-muted">
      {!line.make_fresh && line.stock_on_hand != null && (
        <span data-testid="maker-tree-on-hand">
          {t("tree.onHand", {
            qty: formatQuantityLocalized(t, line.stock_on_hand, line.unit),
          })}
        </span>
      )}
      <Checkbox
        touchTarget
        label={t("tree.makeFresh")}
        title={t("tree.makeFreshHint")}
        checked={line.make_fresh}
        disabled={!canManage || update.isPending}
        onChange={(e) =>
          update.mutate(
            {
              recipeId: line.recipe_id,
              lineId: line.id,
              data: { make_fresh: e.target.checked },
            },
            {
              onError: (err) =>
                toast.error(extractApiError(err, t("tree.makeFreshFailed"))),
            },
          )
        }
        data-testid={`maker-tree-make-fresh-${line.id}`}
      />
    </span>
  );
}
