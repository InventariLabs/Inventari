import { useTranslation } from "react-i18next";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useOpenDraftsOfRecipe } from "@/modules/maker/hooks/useOpenDraftsOfRecipe";
import type { BomLine, MakerRecipe } from "@/modules/maker/types/maker";

/**
 * The question before an ingredient leaves a BOM. It names how many open
 * drafts read the BOM when they close, because removing the line changes
 * every one of them.
 */
export function RemoveIngredientDialog({
  recipe,
  line,
  onConfirm,
  onCancel,
}: {
  recipe: MakerRecipe;
  line: BomLine | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation("maker");
  const openDrafts = useOpenDraftsOfRecipe(recipe, line !== null);
  const question = t("composition.removeConfirm.description", {
    name: line?.child_template_name ?? line?.child_template_id ?? "",
  });
  return (
    <ConfirmDialog
      open={line !== null}
      title={t("composition.removeConfirm.title")}
      message={
        openDrafts > 0
          ? `${question} ${t("composition.openDraftsChange", { count: openDrafts })}`
          : question
      }
      variant="danger"
      confirmLabel={t("composition.removeIngredient")}
      onConfirm={onConfirm}
      onCancel={onCancel}
    />
  );
}
