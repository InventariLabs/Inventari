import { useState } from "react";
import { X, Search, Check, Loader2, BookOpen } from "lucide-react";
import { useTranslation } from "react-i18next";
import { shoppingListsApi } from "../api/shopping-lists";
import { useRecipeOptions } from "../hooks/useShoppingLists";
import { useModules } from "@/contexts/ModulesContext";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";
import { onOtherListsMessage } from "@/modules/shared/lib/shoppingOverlap";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { QueryError } from "@/components/ui/QueryResult";
import { Sheet, SheetActions, SheetFooter } from "@/components/ui/Sheet";

interface Props {
  listId: string;
  onClose: () => void;
  onSuccess: () => void;
}

export default function AddFromRecipesModal({
  listId,
  onClose,
  onSuccess,
}: Props) {
  const { t } = useTranslation("shopping_lists");
  const { isModuleEnabled } = useModules();
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  const { data, isLoading, isError, refetch } = useRecipeOptions({
    search: search || undefined,
    limit: 50,
  });
  const recipes = data?.items ?? [];

  const recipesEnabled = isModuleEnabled("recipes");

  function toggleRecipe(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  async function handleSubmit() {
    if (selected.size === 0) return;
    setSubmitting(true);
    setAddError(null);
    try {
      // The route lives in the recipes module: it is the side that knows how
      // to price a recipe against stock (see `shoppingListsApi`).
      const result = await shoppingListsApi.addFromRecipes({
        recipe_ids: Array.from(selected),
        shopping_list_id: listId,
      });
      // A line topped up counts as written: the list changed by it.
      const written = result.added_count + (result.raised_count ?? 0);
      const listed = result.already_listed_count ?? 0;
      if (written === 0 && listed > 0) {
        // Nothing added because the list asks for it all already, as the
        // recipe screen says: "Added 0 ingredients" read as "nothing was
        // missing" or as a failure.
        toast.info(t("addFromRecipes.alreadyListed"));
      } else {
        toast.success(
          t("addFromRecipes.success", {
            count: written,
            defaultValue: `Added ${written} ingredients`,
          }),
        );
      }
      // The same goods may already stand on another open list.
      const overlap = onOtherListsMessage(t, result.on_other_lists);
      if (overlap) toast.warning(overlap);
      onSuccess();
    } catch (err) {
      setAddError(extractApiError(err, t("addFromRecipes.failed")));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Sheet
      open
      onClose={onClose}
      backdropOpacity={60}
      aria-label={t("addFromRecipes.title", {
        defaultValue: "Add from recipes",
      })}
    >
      <div className="p-6 pb-0">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-violet-50 text-violet-600 rounded-xl">
              <BookOpen size={20} />
            </div>
            <h3 className="text-lg font-semibold text-on">
              {t("addFromRecipes.title", {
                defaultValue: "Add from recipes",
              })}
            </h3>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            aria-label={t("common:actions.close")}
          >
            <X size={24} />
          </Button>
        </div>

        <Input
          wrapperClassName="mb-4"
          leftIcon={<Search size={14} />}
          aria-label={t("addFromRecipes.search")}
          placeholder={t("addFromRecipes.search")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <div className="flex-1 overflow-y-auto px-6 pb-2">
        {!recipesEnabled && (
          <p className="text-sm text-on-muted text-center py-8">
            {t("addFromRecipes.recipesDisabled")}
          </p>
        )}
        {recipesEnabled && isLoading && (
          <div className="flex justify-center py-8">
            <Loader2 size={24} className="animate-spin text-on-muted" />
          </div>
        )}
        {recipesEnabled && isError && (
          <QueryError onRetry={() => void refetch()} />
        )}
        {recipesEnabled && !isLoading && !isError && recipes.length === 0 && (
          <p className="text-sm text-on-muted text-center py-8">
            {t("addFromRecipes.noRecipes")}
          </p>
        )}
        {recipesEnabled &&
          !isLoading &&
          recipes.map((recipe) => (
            <Button
              size="content"
              key={recipe.id}
              type="button"
              variant="outline"
              onClick={() => toggleRecipe(recipe.id)}
              className="w-full justify-start gap-3 p-3 rounded-xl border mb-2 transition-colors text-left"
            >
              <div
                className={`w-5 h-5 rounded-md border flex items-center justify-center shrink-0 transition-colors ${
                  selected.has(recipe.id)
                    ? "bg-primary-600 border-primary-600 text-white"
                    : "border-border"
                }`}
              >
                {selected.has(recipe.id) && <Check size={12} />}
              </div>
              {recipe.image_url ? (
                <img
                  src={recipe.image_url}
                  alt={recipe.name}
                  loading="lazy"
                  className="w-10 h-10 rounded-lg object-cover flex-shrink-0"
                />
              ) : (
                <div className="w-10 h-10 rounded-lg bg-muted flex-shrink-0 flex items-center justify-center">
                  <BookOpen size={16} className="text-on-muted" />
                </div>
              )}
              <div className="flex-1 min-w-0">
                <span className="text-sm font-medium truncate block">
                  {recipe.name}
                </span>
                {recipe.tags && recipe.tags.length > 0 && (
                  <span className="text-[10px] text-on-muted">
                    {recipe.tags.slice(0, 3).join(", ")}
                  </span>
                )}
              </div>
            </Button>
          ))}
      </div>

      {addError && (
        <p
          role="alert"
          className="mx-6 mb-2 rounded-xl bg-red-50 px-3 py-2 text-sm text-on-danger"
        >
          {addError}
        </p>
      )}

      <SheetFooter>
        <SheetActions className="gap-3">
          <Button variant="outline" onClick={onClose}>
            {t("modal.cancel")}
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={selected.size === 0 || submitting}
            className="gap-2"
          >
            {submitting ? (
              <Loader2 size={18} className="animate-spin" />
            ) : (
              <BookOpen size={18} />
            )}
            {submitting
              ? t("addFromRecipes.adding")
              : t("addFromRecipes.addSelected", {
                  count: selected.size,
                })}
          </Button>
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}
