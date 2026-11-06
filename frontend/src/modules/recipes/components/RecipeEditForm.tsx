import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { extractApiError } from "@/lib/errors";
import { useRecipe } from "@/modules/recipes/hooks/useRecipes";
import type { RecipeCreate, RecipeList } from "@/modules/recipes/types/core";
import RecipeForm from "./RecipeForm";

interface Props {
  /** The clicked grid row — it carries the ingredient count, not the list. */
  recipe: RecipeList;
  onSubmit: (data: RecipeCreate) => void;
  onCancel: () => void;
  isLoading?: boolean;
}

/**
 * Seeds the edit form from the recipe detail, never from the grid row: the
 * list item has ingredients_total but no ingredients array, so a form seeded
 * from it wrote the empty list back on Save.
 */
export default function RecipeEditForm({
  recipe,
  onSubmit,
  onCancel,
  isLoading,
}: Props) {
  const { t } = useTranslation(["recipes", "common"]);
  const detail = useRecipe(recipe.id);

  useEffect(() => {
    if (!detail.isError) return;
    toast.error(extractApiError(detail.error, t("errors.load_failed")));
    onCancel();
  }, [detail.isError, detail.error, onCancel, t]);

  // A failed read has already toasted and closed the form; it renders nothing.
  // A pending one shows the sheet at once, so the click is answered while the
  // detail travels — on a cold cache the form used to appear only when it
  // landed, and the click looked dead. The same sheet then holds the form.
  if (detail.isError) return null;
  return (
    <RecipeForm
      loading={!detail.data}
      initial={detail.data}
      onSubmit={onSubmit}
      onCancel={onCancel}
      isLoading={isLoading}
    />
  );
}
