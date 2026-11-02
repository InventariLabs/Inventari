import { ChefHat, Loader2 } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/Button";
import { QueryError } from "@/components/ui/QueryResult";
import { RecipeCard } from "./RecipeCard";
import type {
  RecipeCollection,
  RecipeList,
} from "@/modules/recipes/types/core";
import type { TFunction } from "i18next";

interface RecipeGridProps {
  recipes: RecipeList[];
  isLoading: boolean;
  isError: boolean;
  page: number;
  pageSize: number;
  /** total number of matching recipes — drives the real last page. */
  total: number;
  tab: string;
  search: string;
  selectedTags: string[];
  tagColorMap: Map<string, string | null>;
  selectionMode: boolean;
  selectedIds: Set<string>;
  dragEnabled: boolean;
  /** Whether the reader may change recipes; threaded to every card. */
  canWrite?: boolean;
  onToggleSelect: (id: string) => void;
  onRetry: () => void;
  onToggleFavorite: (recipe: RecipeList) => void;
  onEdit: (recipe: RecipeList) => void;
  onDelete: (id: string) => void;
  onDuplicate: (recipe: RecipeList) => void;
  onTagClick: (tag: string) => void;
  onPageChange: (page: number) => void;
  /** when the "available" tab is empty, distinguish "nothing linked"
   *  from "linked but out of stock" — only the latter points to inventory. */
  hasLinkedIngredients?: boolean;
  /** The near misses the availability query returned. An empty "ready" list
   *  with these on hand is a recipe one ingredient short, not a bare pantry. */
  almostRecipes?: RecipeList[];
  onGoToAllRecipes?: () => void;
  /** "No recipes yet" offers creating one right there. */
  onCreateRecipe?: () => void;
  /** The collection the grid is showing, if any. Its empty state offers
   *  adding a recipe that already exists rather than creating a new one. */
  activeCollection?: RecipeCollection | null;
  onAddExistingRecipes?: () => void;
  t: TFunction;
}

export function RecipeGrid({
  recipes,
  isLoading,
  isError,
  page,
  pageSize,
  total,
  tab,
  search,
  selectedTags,
  tagColorMap,
  selectionMode,
  selectedIds,
  dragEnabled,
  canWrite = true,
  onToggleSelect,
  onRetry,
  onToggleFavorite,
  onEdit,
  onDelete,
  onDuplicate,
  onTagClick,
  onPageChange,
  hasLinkedIngredients = true,
  almostRecipes,
  onGoToAllRecipes,
  onCreateRecipe,
  activeCollection,
  onAddExistingRecipes,
  t,
}: RecipeGridProps) {
  if (isLoading) {
    return (
      <div className="flex justify-center items-center py-16">
        <Loader2 className="animate-spin text-on-muted" size={28} />
      </div>
    );
  }

  if (isError) {
    return <QueryError onRetry={onRetry} />;
  }

  if (recipes.length === 0) {
    return (
      <RecipeGridEmpty
        tab={tab}
        search={search}
        selectedTags={selectedTags}
        canWrite={canWrite}
        hasLinkedIngredients={hasLinkedIngredients}
        almostRecipes={almostRecipes}
        activeCollection={activeCollection}
        onGoToAllRecipes={onGoToAllRecipes}
        onCreateRecipe={onCreateRecipe}
        onAddExistingRecipes={onAddExistingRecipes}
        t={t}
      />
    );
  }

  return (
    <>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {recipes.map((recipe) => (
          <RecipeCard
            canWrite={canWrite}
            key={recipe.id}
            recipe={recipe}
            selectedTags={selectedTags}
            tagColorMap={tagColorMap}
            selectionMode={selectionMode}
            selected={selectedIds.has(recipe.id)}
            dragEnabled={dragEnabled}
            onToggleSelect={onToggleSelect}
            onToggleFavorite={onToggleFavorite}
            onEdit={onEdit}
            onDelete={onDelete}
            onDuplicate={onDuplicate}
            onTagClick={onTagClick}
            linkTo={`/recipes/${recipe.id}`}
            t={t}
          />
        ))}
      </div>

      {/* Pagination — only when there is more than one page.
 the last page comes from the real total, not from
          guessing "the page is full so there must be another". */}
      {tab !== "available" && (page > 0 || total > pageSize) && (
        <div className="flex items-center justify-center gap-3 mt-4 pb-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => onPageChange(Math.max(0, page - 1))}
            disabled={page === 0}
            aria-label={t("common:a11y.previousPage")}
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polyline points="15 18 9 12 15 6" />
            </svg>
          </Button>
          <span className="text-sm text-on-secondary tabular-nums">
            {page + 1}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => onPageChange(page + 1)}
            disabled={(page + 1) * pageSize >= total}
            aria-label={t("common:a11y.nextPage")}
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polyline points="9 18 15 12 9 6" />
            </svg>
          </Button>
        </div>
      )}
    </>
  );
}

type GridEmptyCase =
  | "availableUnlinked"
  | "available"
  | "favorites"
  | "search"
  | "tags"
  | "collection"
  | "collectionReadOnly"
  | "noRecipes"
  | "noRecipesReadOnly";

/**
 * Which emptiness this is. The order matters: a search or a tag filter inside
 * a collection is the search's emptiness, not the collection's, so those win.
 * The collection only speaks for itself when nothing else narrows the list.
 */
function gridEmptyCase(input: {
  tab: string;
  search: string;
  hasTagFilter: boolean;
  hasLinkedIngredients: boolean;
  hasCollection: boolean;
  canWrite: boolean;
}): GridEmptyCase {
  if (input.tab === "available") {
    // An empty "I can cook" list has two causes — nothing linked to stock
    // (point at linking) vs. linked but out of stock (point at inventory).
    return input.hasLinkedIngredients ? "available" : "availableUnlinked";
  }
  if (input.tab === "favorites") return "favorites";
  if (input.search) return "search";
  if (input.hasTagFilter) return "tags";
  // A reader who cannot add recipes is not invited to: the invitation has no
  // button behind it for them.
  if (input.hasCollection) {
    return input.canWrite ? "collection" : "collectionReadOnly";
  }
  return input.canWrite ? "noRecipes" : "noRecipesReadOnly";
}

/**
 * One copy per emptiness. Each entry is a function taking `t` rather than a
 * pair of key strings: the catalogue keys have to stand as literals inside
 * real `t()` calls, or the orphan-key gate reads this map as ten keys nobody
 * uses — a map of strings is invisible to it, a map of calls is the usage it
 * checks for.
 */
const EMPTY_COPY: Record<
  GridEmptyCase,
  (t: TFunction) => { title: string; description: string }
> = {
  availableUnlinked: (t) => ({
    title: t("recipes:empty.no_available_unlinked"),
    description: t("recipes:empty.no_available_unlinked_desc"),
  }),
  available: (t) => ({
    title: t("recipes:empty.no_available"),
    description: t("recipes:empty.no_available_desc"),
  }),
  favorites: (t) => ({
    title: t("recipes:empty.no_favorites"),
    description: t("recipes:empty.no_favorites_desc"),
  }),
  search: (t) => ({
    title: t("recipes:empty.no_results"),
    description: t("recipes:empty.no_results_desc"),
  }),
  tags: (t) => ({
    title: t("recipes:empty.no_tag_results"),
    description: t("recipes:empty.no_tag_results_desc"),
  }),
  collection: (t) => ({
    title: t("recipes:empty.no_collection_title"),
    description: t("recipes:empty.no_collection_desc"),
  }),
  collectionReadOnly: (t) => ({
    title: t("recipes:empty.no_collection_title"),
    description: t("recipes:empty.no_collection_readonly_desc"),
  }),
  noRecipes: (t) => ({
    title: t("recipes:empty.no_recipes"),
    description: t("recipes:empty.no_recipes_desc"),
  }),
  noRecipesReadOnly: (t) => ({
    title: t("recipes:empty.no_recipes"),
    description: t("recipes:empty.no_recipes_readonly_desc"),
  }),
};

/**
 * The "nothing ready" sentence, naming the near misses when there are any.
 *
 * An empty "ready" list with near misses on hand is not a bare pantry: the
 * one recipe is an ingredient short, and the sentence can name it. Several
 * near misses are counted and pointed at the "Almost" half of the tab. The
 * keys stand as literals in real `t()` calls for the same reason as
 * `EMPTY_COPY`: a key assembled elsewhere is a key the orphan gate reads as
 * unused.
 */
function almostDescription(t: TFunction, almost: RecipeList[]): string | null {
  if (almost.length === 1 && almost[0].missing_names.length > 0) {
    return t("recipes:empty.no_available_missing", {
      name: almost[0].name,
      ingredients: almost[0].missing_names.join(", "),
    });
  }
  if (almost.length > 0) {
    return t("recipes:empty.no_available_almost", { count: almost.length });
  }
  return null;
}

/**
 * The empties of this grid, told apart.
 *
 * Extracted from `RecipeGrid` because the branch count belongs to the
 * message, not to the list: which sentence to show, whether the "available"
 * tab is empty for want of links or for want of stock, and whether to offer
 * the first recipe at all.
 */
function RecipeGridEmpty({
  tab,
  search,
  selectedTags,
  canWrite,
  hasLinkedIngredients,
  almostRecipes,
  activeCollection,
  onGoToAllRecipes,
  onCreateRecipe,
  onAddExistingRecipes,
  t,
}: {
  tab: string;
  search: string;
  selectedTags: string[];
  canWrite: boolean;
  hasLinkedIngredients?: boolean;
  almostRecipes?: RecipeList[];
  activeCollection?: RecipeCollection | null;
  onGoToAllRecipes?: () => void;
  onCreateRecipe?: () => void;
  onAddExistingRecipes?: () => void;
  t: TFunction;
}) {
  const emptyCase = gridEmptyCase({
    tab,
    search,
    hasTagFilter: selectedTags.length > 0,
    hasLinkedIngredients: hasLinkedIngredients ?? true,
    hasCollection: Boolean(activeCollection),
    canWrite,
  });
  const copy = EMPTY_COPY[emptyCase](t);
  const availableUnlinked = emptyCase === "availableUnlinked";

  const description =
    emptyCase === "available"
      ? (almostDescription(t, almostRecipes ?? []) ?? copy.description)
      : copy.description;

  return (
    <div className="text-center py-16">
      <ChefHat size={48} className="text-on-muted mx-auto mb-3" />
      <p className="text-base font-medium text-on-secondary">{t(copy.title)}</p>
      <p className="text-sm text-on-muted mt-1">{t(description)}</p>
      {availableUnlinked && onGoToAllRecipes && (
        <Button
          variant="link"
          size="sm"
          onClick={onGoToAllRecipes}
          className="inline-flex items-center gap-1.5 mt-4 text-sm font-medium text-primary-600"
        >
          {t("recipes:empty.link_ingredients_cta")}
        </Button>
      )}
      {emptyCase === "available" && (
        <Link
          to="/inventory/items"
          className="inline-flex items-center gap-1.5 mt-4 text-sm font-medium text-primary-600 hover:underline"
        >
          {t("recipes:empty.go_to_inventory")}
        </Link>
      )}
      {emptyCase === "collection" && onAddExistingRecipes && canWrite && (
        <Button
          variant="outline"
          size="sm"
          onClick={onAddExistingRecipes}
          className="mt-4"
        >
          {t("recipes:empty.add_existing_recipes")}
        </Button>
      )}
      {emptyCase === "noRecipes" && onCreateRecipe && canWrite && (
        <Button
          variant="outline"
          size="sm"
          onClick={onCreateRecipe}
          className="mt-4"
        >
          {t("recipes:actions.new_recipe")}
        </Button>
      )}
    </div>
  );
}
