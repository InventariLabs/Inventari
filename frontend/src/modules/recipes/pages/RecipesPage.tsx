import { extractApiError, followUpError } from "@/lib/errors";
import { useDndA11y, useDndSensors } from "@/lib/dndA11y";
import { useState, useEffect, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  DndContext,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { toast } from "sonner";
import {
  useRecipes,
  useAvailableRecipes,
  useCreateRecipe,
  useUpdateRecipe,
  useDeleteRecipe,
  useDuplicateRecipe,
  useBulkDeleteRecipes,
  useBulkTagRecipes,
  useRecipeTags,
  useToggleRecipeFavorite,
  useRecipeCollections,
  useAddRecipeToCollection,
  useUploadRecipeImage,
  type RecipeTagFilters,
} from "../hooks/useRecipes";
import RecipeEditForm from "../components/RecipeEditForm";
import RecipeForm from "../components/RecipeForm";
import { TagFilterChips } from "../components/TagFilterChips";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { TagsPanel } from "../components/TagsPanel";
import { RecipeGrid } from "../components/RecipeGrid";
import { RecipeBulkBar } from "../components/RecipeBulkBar";
import { CollectionAddRecipesModal } from "../components/CollectionAddRecipesModal";
import {
  CollectionsChips,
  CollectionsLoadFailed,
  CollectionsSidebar,
  CollectionDialogs,
  useCollectionManager,
} from "../components/CollectionsPanel";
import { RecipeImportManager } from "../components/RecipeImportManager";
import { RecipesPageHeaderActions } from "../components/RecipesPageHeaderActions";
import type {
  RecipeList,
  RecipeCollection,
  RecipeCreate,
} from "@/modules/recipes/types/core";
import type { RecipeTagItem } from "@/modules/recipes/types/nutrition";
import type { TFunction } from "i18next";
import type { ListControlBarSecondaryFilter } from "@/components/ui/ListControlBar";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { showListControls } from "@/hooks/useFilteredList";
import { ListControlBar } from "@/components/ui/ListControlBar";

type FilterTab = "all" | "available" | "favorites";

/** Which half of the "I can cook" tab is being read. */
type CookScope = "ready" | "almost";

/**
 * Everything the recipe asks for is on the shelf.
 *
 * The tab used to show whatever was half covered, so a recipe reading "3 of 4
 * in stock" sat under a heading promising it could be cooked. The two are
 * split now, and both are named on screen.
 */
const READY_TO_COOK = 1;

/** The near misses, kept to a list short enough to read. */
const ALMOST_THRESHOLD = 0.5;

const isReadyToCook = (recipe: RecipeList) =>
  (recipe.match_percentage ?? 0) >= READY_TO_COOK;

/** the two halves of the "I can cook" tab, named and countable. */
function cookScopeChips(
  t: TFunction,
  scope: CookScope,
  counts: { ready: number; almost: number },
  onScope: (scope: CookScope) => void,
): ListControlBarSecondaryFilter[] {
  return [
    {
      key: "cook-ready",
      label: t("filters.ready_to_cook", { total: counts.ready }),
      active: scope === "ready",
      onToggle: () => onScope("ready"),
    },
    {
      key: "cook-almost",
      label: t("filters.almost_ready", { total: counts.almost }),
      active: scope === "almost",
      onToggle: () => onScope("almost"),
    },
  ];
}

/** sort chips for the all/favorites tabs (kept out of the page
 *  component so its cyclomatic complexity stays under the lint cap). */
function sortFilterChips(
  t: TFunction,
  sort: "newest" | "name",
  onSort: (sort: "newest" | "name") => void,
): ListControlBarSecondaryFilter[] {
  return [
    {
      key: "sort-newest",
      label: t("filters.sort_newest"),
      active: sort === "newest",
      onToggle: () => onSort("newest"),
    },
    {
      key: "sort-name",
      label: t("filters.sort_name"),
      active: sort === "name",
      onToggle: () => onSort("name"),
    },
  ];
}

/** The control bar's chips: cook scope on the "available" tab, sort elsewhere. */
function secondaryChips(
  t: TFunction,
  view: { tab: FilterTab; cookScope: CookScope; sort: "newest" | "name" },
  [ready, almost]: [number, number],
  set: {
    setCookScope: (scope: CookScope) => void;
    setSort: (sort: "newest" | "name") => void;
    setPage: (page: number) => void;
  },
): ListControlBarSecondaryFilter[] {
  return view.tab === "available"
    ? cookScopeChips(t, view.cookScope, { ready, almost }, (next) => {
        set.setCookScope(next);
        set.setPage(0);
      })
    : sortFilterChips(t, view.sort, (next) => {
        set.setSort(next);
        set.setPage(0);
      });
}

/**
 * Whether the "available" tab's emptiness is about linked-but-out-of-stock or
 * about ingredients never linked at all. The first page of the all-recipes
 * list answers it; the empty state says which, so the two do not read alike.
 */
function hasAnyLinkedIngredients(
  tab: FilterTab,
  listData: { items?: RecipeList[] } | undefined,
): boolean {
  if (tab !== "available") return true;
  return (listData?.items ?? []).some((r) => r.ingredients_linked > 0);
}

/** the list API returns {items, total} — the "available" tab keeps
 *  its own array shape; unwrap both to the same page shape here so the
 *  component stays under the cyclomatic complexity cap. */
function unwrapRecipeList(
  tab: FilterTab,
  listData: { items?: RecipeList[]; total?: number } | undefined,
  availableRecipes: RecipeList[] | undefined,
): { recipes: RecipeList[]; total: number } {
  if (tab === "available") {
    const recipes = availableRecipes ?? [];
    return { recipes, total: recipes.length };
  }
  return { recipes: listData?.items ?? [], total: listData?.total ?? 0 };
}

/**
 * Whether the reader has narrowed the list themselves.
 *
 * Five ways to narrow this page, so the question lives outside the component —
 * both to keep it under the complexity cap and because "has the reader
 * narrowed it" is one idea, not five conditions in a render body.
 */
function isListNarrowed(state: {
  search: string;
  tab: FilterTab;
  sort: string;
  selectedTags: string[];
  activeCollectionId: string | null;
}): boolean {
  return (
    state.search.trim().length > 0 ||
    state.tab !== "all" ||
    state.sort !== "newest" ||
    state.selectedTags.length > 0 ||
    state.activeCollectionId !== null
  );
}

/** Collections nest, so the selected one may sit anywhere in the tree. */
function findCollection(
  nodes: RecipeCollection[],
  id: string | null,
): RecipeCollection | null {
  if (!id) return null;
  for (const node of nodes) {
    if (node.id === id) return node;
    const child = findCollection(node.children, id);
    if (child) return child;
  }
  return null;
}

/** How many of these recipes carry each tag — the answer a click on the
 *  chip would produce. Used where the server cannot know the view: the
 *  availability query returns the whole list, so its counts are exact. */
function countTags(recipes: RecipeList[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const recipe of recipes) {
    for (const tag of recipe.tags ?? []) {
      counts.set(tag, (counts.get(tag) ?? 0) + 1);
    }
  }
  return counts;
}

/** The narrowing the chips answer for, in the shape the list query sends. */
function tagScopeFor(state: {
  tab: FilterTab;
  search: string;
  tagsParam?: string;
  activeCollectionId: string | null;
}): RecipeTagFilters {
  if (state.tab === "available") return { tags: state.tagsParam };
  if (state.tab === "favorites") {
    return {
      search: state.search || undefined,
      tags: state.tagsParam,
      is_favorite: true,
    };
  }
  return {
    search: state.search || undefined,
    tags: state.tagsParam,
    collection_id: state.activeCollectionId ?? undefined,
  };
}

/** In the availability tab the whole matching list is on the client, so the
 *  chips count it; the server cannot match stock and would count strangers. */
function tagsForView(
  tags: RecipeTagItem[],
  tab: FilterTab,
  availableRecipes: RecipeList[],
  selectedTags: string[],
): RecipeTagItem[] {
  if (tab !== "available") return tags;
  const counts = countTags(availableRecipes);
  return tags
    .map((tag) => ({ ...tag, count: counts.get(tag.name) ?? 0 }))
    .filter((tag) => tag.count > 0 || selectedTags.includes(tag.name));
}

/** The collection picker, mounted only once a collection has asked for it. */
function CollectionAddRecipesOverlay({
  collection,
  onClose,
}: {
  collection: RecipeCollection | null;
  onClose: () => void;
}) {
  if (!collection) return null;
  return (
    <CollectionAddRecipesModal collection={collection} onClose={onClose} />
  );
}

/** A photo that failed after its recipe was saved: only the photo failed. */
const photoFailed = (error: unknown, fallback: string) =>
  toast.error(followUpError(error, fallback));

export default function RecipesPage() {
  const { t } = useTranslation(["recipes", "common"]);
  const navigate = useNavigate();
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("recipes");
  const toggleFavoriteMutation = useToggleRecipeFavorite();

  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<FilterTab>("all");
  const [sort, setSort] = useState<"newest" | "name">("newest");
  const [cookScope, setCookScope] = useState<CookScope>("ready");
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [showForm, setShowForm] = useState(false);
  // The grid hands over a list row, which carries the ingredient count but no
  // ingredients; RecipeEditForm reads the detail before opening.
  const [editRecipe, setEditRecipe] = useState<RecipeList | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [showImport, setShowImport] = useState(false);
  const [showTags, setShowTags] = useState(false);
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 50;

  // Multi-select mode
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // Collections
  const [activeCollectionId, setActiveCollectionId] = useState<string | null>(
    null,
  );
  const [addingToCollection, setAddingToCollection] =
    useState<RecipeCollection | null>(null);
  const [draggingRecipeId, setDraggingRecipeId] = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();

  // A screen whose empty state cannot create a recipe sends the reader here
  // with "?new=1" — the form opens on arrival instead of asking them to find
  // the button they were just promised.
  useEffect(() => {
    if (searchParams.get("new") !== "1") return;
    setShowForm(true);
    const next = new URLSearchParams(searchParams);
    next.delete("new");
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  const collectionsQuery = useRecipeCollections();
  const collections = collectionsQuery.data ?? [];
  const activeCollection = findCollection(collections, activeCollectionId);

  const tagsParam =
    selectedTags.length > 0 ? selectedTags.join(",") : undefined;

  // The chips count the view the list is showing: search, tag, favorite and
  // collection narrowing go to the server with the same shape the list query
  // sends, so a chip never promises results the reader cannot see.
  const tagScope = tagScopeFor({ tab, search, tagsParam, activeCollectionId });
  const tagsQuery = useRecipeTags(tagScope);

  const allRecipesQuery = useRecipes({
    search: search || undefined,
    tags: tagsParam,
    collection_id: activeCollectionId ?? undefined,
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
    sort,
  });
  const favoritesQuery = useRecipes({
    search: search || undefined,
    tags: tagsParam,
    is_favorite: true,
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
    sort,
  });
  // One reading covers both chips: the server is asked for the near misses as
  // well, and the page decides which half is on screen.
  const availableQuery = useAvailableRecipes({
    tags: tagsParam,
    min_match: ALMOST_THRESHOLD,
  });

  const createMutation = useCreateRecipe();
  const uploadImageMutation = useUploadRecipeImage();
  const updateMutation = useUpdateRecipe();
  const deleteMutation = useDeleteRecipe();
  const duplicateMutation = useDuplicateRecipe();
  const bulkDeleteMutation = useBulkDeleteRecipes();
  const bulkTagMutation = useBulkTagRecipes();
  const addToCollectionMutation = useAddRecipeToCollection();

  const dragSensors = useDndSensors(6, false);
  const dndA11y = useDndA11y();

  const toggleSelectionMode = useCallback(() => {
    setSelectionMode((v) => !v);
    setSelectedIds(new Set());
  }, []);

  const activeQuery =
    tab === "all"
      ? allRecipesQuery
      : tab === "favorites"
        ? favoritesQuery
        : availableQuery;

  const availableRecipes =
    (availableQuery.data as RecipeList[] | undefined) ?? [];
  const readyRecipes = availableRecipes.filter(isReadyToCook);
  const almostRecipes = availableRecipes.filter((r) => !isReadyToCook(r));

  // In this tab the server counts recipes it cannot match against stock, so
  // the numbers come from the list the availability query returned instead.
  const allTags = tagsForView(
    tagsQuery.data ?? [],
    tab,
    availableRecipes,
    selectedTags,
  );
  const tagColorMap = new Map(allTags.map((tg) => [tg.name, tg.color ?? null]));

  // unwrap {items, total} (all/favorites) or array (available)
  const { recipes, total } = unwrapRecipeList(
    tab,
    activeQuery.data as { items?: RecipeList[]; total?: number } | undefined,
    cookScope === "ready" ? readyRecipes : almostRecipes,
  );
  const isLoading = activeQuery.isLoading;
  const isError = activeQuery.isError;

  const controlsVisible = showListControls({
    isLoading,
    total,
    isNarrowed: isListNarrowed({
      search,
      tab,
      sort,
      selectedTags,
      activeCollectionId,
    }),
  });

  const selectCollection = (id: string | null) => {
    setActiveCollectionId(id);
    setPage(0);
  };

  // Shared create/rename/delete state for the mobile chips and the desktop
  // sidebar — one source of truth, both surfaces.
  const collectionManager = useCollectionManager({
    t,
    activeCollectionId,
    onSelect: selectCollection,
  });

  useEffect(() => {
    setHeader({
      actions: (
        <RecipesPageHeaderActions
          canWrite={canWrite}
          selectionMode={selectionMode}
          hasRecipes={total > 0}
          hasTags={allTags.length > 0}
          t={t}
          onToggleSelectionMode={toggleSelectionMode}
          onToggleTags={() => setShowTags((v) => !v)}
          onToggleImport={() => setShowImport((v) => !v)}
          onNewCollection={collectionManager.openCreate}
          onNewRecipe={() => setShowForm(true)}
        />
      ),
    });
    return () => setHeader({});
  }, [
    t,
    setHeader,
    navigate,
    selectionMode,
    toggleSelectionMode,
    total,
    allTags.length,
    collectionManager.openCreate,
    canWrite,
  ]);

  const hasLinkedIngredients = hasAnyLinkedIngredients(
    tab,
    allRecipesQuery.data as { items?: RecipeList[] } | undefined,
  );

  const handleCreate = async (
    data: Parameters<typeof createMutation.mutateAsync>[0],
    imageFile?: File | null,
  ) => {
    try {
      const created = await createMutation.mutateAsync(data);
      // the image endpoint needs an existing recipe id, so a photo
      // picked in the create form is uploaded right after creation.
      // The recipe exists by now: a refused photo must not read as "not saved".
      if (imageFile) {
        await uploadImageMutation
          .mutateAsync({ id: created.id, file: imageFile })
          .catch((e: unknown) => photoFailed(e, t("errors.image_failed")));
      }
      toast.success(t("toasts.created"));
      setShowForm(false);
    } catch (error) {
      toast.error(extractApiError(error, t("errors.save_failed")));
    }
  };

  const handleUpdate = async (data: RecipeCreate) => {
    if (!editRecipe) return;
    try {
      await updateMutation.mutateAsync({ id: editRecipe.id!, data });
      toast.success(t("toasts.saved"));
      setEditRecipe(null);
    } catch (error) {
      toast.error(extractApiError(error, t("errors.save_failed")));
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteMutation.mutateAsync(id);
      toast.success(t("toasts.deleted"));
      setDeleteConfirmId(null);
    } catch (error) {
      toast.error(extractApiError(error, t("errors.delete_failed")));
    }
  };

  const handleDuplicate = async (recipe: RecipeList) => {
    try {
      const copy = await duplicateMutation.mutateAsync(recipe.id);
      toast.success(t("toasts.duplicated"));
      navigate(`/recipes/${copy.id}`);
    } catch (error) {
      toast.error(extractApiError(error, t("errors.save_failed")));
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  // select / deselect the whole current page in one tap
  const allSelected =
    recipes.length > 0 && recipes.every((r) => selectedIds.has(r.id));
  const toggleSelectAll = () => {
    if (allSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(recipes.map((r) => r.id)));
    }
  };

  const handleBulkAddToCollection = async (collectionId: string) => {
    if (selectedIds.size === 0) return;
    try {
      await Promise.all(
        Array.from(selectedIds).map((recipeId) =>
          addToCollectionMutation.mutateAsync({ collectionId, recipeId }),
        ),
      );
      toast.success(t("collections.added"));
    } catch (error) {
      toast.error(extractApiError(error, t("collections.error")));
    }
  };

  const handleBulkDelete = async () => {
    if (selectedIds.size === 0) return;
    try {
      const result = await bulkDeleteMutation.mutateAsync(
        Array.from(selectedIds),
      );
      toast.success(t("bulk.deleted", { count: result.deleted }));
      setSelectedIds(new Set());
      setSelectionMode(false);
    } catch (error) {
      toast.error(extractApiError(error, t("bulk.error")));
    }
  };

  const handleBulkTag = async (tags: string[]) => {
    if (selectedIds.size === 0 || tags.length === 0) return;
    try {
      await bulkTagMutation.mutateAsync({
        recipeIds: Array.from(selectedIds),
        tags,
      });
      toast.success(t("bulk.tagged"));
    } catch (error) {
      toast.error(extractApiError(error, t("bulk.error")));
    }
  };

  // ── Collections ───────────────────────────────────────────────────────────

  const handleDragStart = useCallback((event: DragStartEvent) => {
    const data = event.active.data.current as
      { type?: string; recipeId?: string } | undefined;
    if (data?.type === "recipe" && data.recipeId) {
      setDraggingRecipeId(data.recipeId);
    }
  }, []);

  const handleDragEnd = useCallback(
    async (event: DragEndEvent) => {
      const { over } = event;
      setDraggingRecipeId(null);
      if (!over) return;
      const overData = over.data.current as
        { type?: string; collectionId?: string } | undefined;
      if (overData?.type !== "collection" || !overData.collectionId) return;
      if (!draggingRecipeId) return;
      try {
        await addToCollectionMutation.mutateAsync({
          collectionId: overData.collectionId,
          recipeId: draggingRecipeId,
        });
        toast.success(t("collections.added"));
      } catch (error) {
        toast.error(extractApiError(error, t("collections.error")));
      }
    },
    [draggingRecipeId, addToCollectionMutation, t],
  );

  const toggleFavorite = async (recipe: RecipeList) => {
    const newValue = !recipe.is_favorite;
    try {
      await toggleFavoriteMutation.mutateAsync({
        recipeId: recipe.id,
        newValue,
      });
    } catch (error) {
      toast.error(extractApiError(error, t("errors.save_failed")));
    }
  };

  const toggleTag = (tag: string) => {
    setSelectedTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
    );
    setPage(0);
  };

  return (
    <DndContext
      sensors={dragSensors}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      accessibility={dndA11y}
    >
      <div className="animate-in fade-in duration-300 motion-reduce:animate-none">
        {/* Chips sit ABOVE the flex row: as a flex child they collapsed the grid. */}
        <CollectionsLoadFailed
          failed={collectionsQuery.isError}
          onRetry={() => void collectionsQuery.refetch()}
          t={t}
        />
        <CollectionsChips
          collections={collections}
          activeCollectionId={activeCollectionId}
          onSelect={selectCollection}
          onOpenCreate={collectionManager.openCreate}
          canWrite={canWrite}
          t={t}
        />
        <div className="flex gap-6 items-start">
          <CollectionsSidebar
            collections={collections}
            activeCollectionId={activeCollectionId}
            onSelect={selectCollection}
            isOverCollection={draggingRecipeId !== null}
            manager={collectionManager}
            canWrite={canWrite}
            t={t}
          />

          <div
            className="flex-1 min-w-0 space-y-6"
            data-testid="recipes-content"
          >
            <ReadOnlyNotice module="recipes" />
            {controlsVisible && (
              <ListControlBar
                search={{
                  value: search,
                  onChange: (v) => {
                    setSearch(v);
                    setPage(0);
                  },
                  placeholder: t("filters.search"),
                }}
                primaryTabs={{
                  value: tab,
                  onChange: (v) => {
                    setTab(v as FilterTab);
                    setPage(0);
                  },
                  options: [
                    { value: "all", label: t("filters.all") },
                    { value: "available", label: t("filters.available") },
                    { value: "favorites", label: t("filters.favorites") },
                  ],
                }}
                // sort chips (all/favorites tabs) + the real result count
                secondaryFilters={secondaryChips(
                  t,
                  { tab, cookScope, sort },
                  [readyRecipes.length, almostRecipes.length],
                  { setCookScope, setSort, setPage },
                )}
                resultCount={total}
                resultCountLabel={t("filters.results", { count: total })}
              />
            )}

            {controlsVisible && tagsQuery.isError && (
              <InlineQueryError
                error={tagsQuery.error}
                onRetry={() => void tagsQuery.refetch()}
              />
            )}

            {controlsVisible && (
              <TagFilterChips
                allTags={allTags}
                selectedTags={selectedTags}
                onToggleTag={toggleTag}
                onClearTags={() => {
                  setSelectedTags([]);
                  setPage(0);
                }}
                clearTagsText={t("filters.clear_tags")}
                showMoreText={t("filters.show_more_tags")}
                showLessText={t("filters.show_less_tags")}
              />
            )}

            <RecipeGrid
              canWrite={canWrite}
              recipes={recipes}
              isLoading={isLoading}
              isError={isError}
              page={page}
              pageSize={PAGE_SIZE}
              total={total}
              tab={tab}
              search={search}
              selectedTags={selectedTags}
              tagColorMap={tagColorMap}
              selectionMode={selectionMode}
              selectedIds={selectedIds}
              dragEnabled={collections.length > 0 && !selectionMode}
              onToggleSelect={toggleSelect}
              onRetry={() => activeQuery.refetch()}
              onToggleFavorite={toggleFavorite}
              onEdit={setEditRecipe}
              onDelete={setDeleteConfirmId}
              onDuplicate={handleDuplicate}
              onTagClick={toggleTag}
              onPageChange={setPage}
              hasLinkedIngredients={hasLinkedIngredients}
              almostRecipes={almostRecipes}
              onGoToAllRecipes={() => setTab("all")}
              onCreateRecipe={() => setShowForm(true)}
              activeCollection={activeCollection}
              onAddExistingRecipes={() =>
                setAddingToCollection(activeCollection)
              }
              t={t}
            />

            {/* Batch action bar — multi-select mode */}
            <RecipeBulkBar
              open={selectionMode}
              selectedCount={selectedIds.size}
              allSelected={allSelected}
              isBusy={bulkTagMutation.isPending || bulkDeleteMutation.isPending}
              collections={collections}
              onSelectAll={toggleSelectAll}
              onTag={handleBulkTag}
              onDelete={handleBulkDelete}
              onAddToCollection={handleBulkAddToCollection}
              onClear={toggleSelectionMode}
              t={t}
            />

            {showForm && (
              <RecipeForm
                onSubmit={handleCreate}
                onCancel={() => setShowForm(false)}
                isLoading={createMutation.isPending}
              />
            )}

            {editRecipe && (
              <RecipeEditForm
                recipe={editRecipe}
                onSubmit={handleUpdate}
                onCancel={() => setEditRecipe(null)}
                isLoading={updateMutation.isPending}
              />
            )}

            <ConfirmDialog
              open={Boolean(deleteConfirmId)}
              title={t("actions.delete")}
              message={
                recipes.find((r) => r.id === deleteConfirmId)?.name ?? ""
              }
              variant="danger"
              confirmLabel={t("actions.delete")}
              cancelLabel={t("common:form.cancel")}
              onConfirm={() => deleteConfirmId && handleDelete(deleteConfirmId)}
              onCancel={() => setDeleteConfirmId(null)}
            />

            {showImport && (
              <RecipeImportManager
                t={t}
                onClose={() => setShowImport(false)}
                onImported={(recipe) => navigate(`/recipes/${recipe.id}`)}
              />
            )}

            <TagsPanel
              isOpen={showTags}
              onClose={() => setShowTags(false)}
              onTagClick={(name) => {
                setSelectedTags((prev) =>
                  prev.includes(name) ? prev : [...prev, name],
                );
                setPage(0);
              }}
              titleText={t("tags_manager.title")}
            />
          </div>
        </div>
      </div>

      {/* Shared collection dialogs (create/rename/delete) — one instance
 for the chips and the sidebar. */}
      <CollectionDialogs manager={collectionManager} t={t} />

      <CollectionAddRecipesOverlay
        collection={addingToCollection}
        onClose={() => setAddingToCollection(null)}
      />
    </DndContext>
  );
}
