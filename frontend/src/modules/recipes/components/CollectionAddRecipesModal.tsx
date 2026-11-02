import { useState } from "react";
import { Check, Loader2, Plus, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Sheet, SheetBody, SheetTitle } from "@/components/ui/Sheet";
import { QueryFailure } from "@/components/ui/QueryResult";
import {
  useAddRecipeToCollection,
  useRecipes,
} from "@/modules/recipes/hooks/useRecipes";
import type { RecipeCollection } from "@/modules/recipes/types/core";

interface CollectionAddRecipesModalProps {
  collection: RecipeCollection;
  onClose: () => void;
}

/**
 * Adds recipes that already exist to an empty collection.
 *
 * A fresh collection's empty state used to offer only "New recipe", which
 * answered a different question than the one the reader had. This picker
 * lists what is already there; clicking a row adds it, and the row says so,
 * so filling a collection is one visit rather than a sequence of them.
 */
export function CollectionAddRecipesModal({
  collection,
  onClose,
}: CollectionAddRecipesModalProps) {
  const { t } = useTranslation("recipes");
  const [search, setSearch] = useState("");
  const [addedIds, setAddedIds] = useState<Set<string>>(new Set());

  const { data, isError, isPending, error, refetch } = useRecipes({
    search: search || undefined,
  });
  const addToCollection = useAddRecipeToCollection();
  const recipes = data?.items ?? [];

  const addOne = async (recipeId: string) => {
    try {
      await addToCollection.mutateAsync({
        collectionId: collection.id,
        recipeId,
      });
      setAddedIds((prev) => new Set(prev).add(recipeId));
      toast.success(t("collections.added"));
    } catch (err) {
      toast.error(extractApiError(err, t("collections.error")));
    }
  };

  return (
    <Sheet
      open
      onClose={onClose}
      zIndex="confirm"
      maxWidth="lg"
      aria-label={t("collections.add_modal_title", { name: collection.name })}
    >
      <SheetBody className="p-5 space-y-4">
        <SheetTitle className="text-sm">
          {t("collections.add_modal_title", { name: collection.name })}
        </SheetTitle>

        <Input
          leftIcon={<Search size={14} />}
          aria-label={t("collections.add_search_placeholder")}
          placeholder={t("collections.add_search_placeholder")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          data-testid="collection-add-search"
        />

        {isError ? (
          <QueryFailure error={error} onRetry={() => refetch()} />
        ) : isPending ? (
          <div className="flex justify-center py-6" role="status">
            <Loader2
              className="animate-spin text-on-muted"
              size={24}
              aria-label={t("common:a11y.loading")}
            />
          </div>
        ) : recipes.length === 0 ? (
          <p className="text-sm text-on-muted text-center py-6">
            {search ? t("collections.add_no_match") : t("collections.add_none")}
          </p>
        ) : (
          <div className="flex flex-col gap-2 max-h-[50vh] overflow-y-auto">
            {recipes.map((recipe) => {
              const added = addedIds.has(recipe.id);
              return (
                <Button
                  key={recipe.id}
                  type="button"
                  variant="outline"
                  size="row"
                  disabled={added}
                  onClick={() => void addOne(recipe.id)}
                  className="justify-between"
                  data-testid={`collection-add-${recipe.id}`}
                >
                  <span className="text-sm font-medium truncate">
                    {recipe.name}
                  </span>
                  <span className="inline-flex items-center gap-1 text-xs text-on-muted shrink-0">
                    {added ? <Check size={16} /> : <Plus size={16} />}
                    {added
                      ? t("collections.added_one")
                      : t("collections.add_one")}
                  </span>
                </Button>
              );
            })}
          </div>
        )}

        <div className="flex justify-end">
          <Button variant="outline" onClick={onClose}>
            {t("common:actions.close")}
          </Button>
        </div>
      </SheetBody>
    </Sheet>
  );
}
