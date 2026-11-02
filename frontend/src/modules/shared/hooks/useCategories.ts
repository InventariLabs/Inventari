import { useQuery } from "@tanstack/react-query";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { categoriesApi } from "@/lib/api/categories";
import type { CategoryDTO } from "@/types";
import { queryKeys } from "@/hooks/queries/keys";
import { invalidation } from "@/lib/api/invalidation";
import { useShowModuleData } from "@/modules/settings/hooks/useOrganization";

/**
 * The raw category list, with every question about scope left to the caller.
 *
 * The call sites were resolved once, when the scope gate was added:
 *
 * - **Names a row (`all`)** — a category already on a record has to resolve
 *   whatever the module-data policy is, or the row reads "Unknown" over a
 *   field that is perfectly well known. These call `useAllCategories`:
 *   the equipment module's own screens (`ImportEquipmentModal`,
 *   `ModelGridCard`, `AssetInfoTab`, `ModelEditModal`, `useEquipmentForm`,
 *   `AssetListPage`, `AddEquipmentPage`), the product detail
 *   (`ItemDetailContent`) and storage detail (`StorageDetailPage`) rows, and
 *   `useQuickAdd`'s name lookup.
 * - **Offers a choice (`scoped`)** — a picker or filter on a general screen
 *   must not offer what the same policy keeps off its lists, or it hands out
 *   a filter that narrows to nothing. These call `useScopedCategories`:
 *   `PutawayMatchFields`, `StockTakeAddItemForm`, `BulkEditModal`,
 *   `ItemEditModal`, `ItemsPage`, `PutawayRulesPage`, and `useQuickAdd`'s
 *   picker.
 * - **Own scope** — `CategoriesPage` and `EquipmentCategoriesPage` are
 *   management screens that pass `excludeModuleContexts` themselves to
 *   include or count hidden rows.
 *
 * `scripts/check-category-scope.mjs` refuses a bare `useCategories()` so a
 * new call site has to say which of the three it is.
 */
export function useCategories(
  includeInactive?: boolean,
  excludeModuleContexts?: boolean,
  withCounts?: boolean,
  options?: { enabled?: boolean },
) {
  return useQuery<CategoryDTO[]>({
    // The flags belong in the key: a list cached without counts cannot answer
    // a caller that asked for them.
    queryKey: [
      ...queryKeys.categories.all,
      { includeInactive, excludeModuleContexts, withCounts },
    ],
    queryFn: () =>
      categoriesApi.getAll(includeInactive, excludeModuleContexts, withCounts),
    enabled: options?.enabled ?? true,
  });
}

/**
 * Every category the organization has, on purpose.
 *
 * The naming twin of `useScopedCategories`: a record already on screen has to
 * be able to say what category it is filed under, whatever the module-data
 * policy keeps off the general pickers. The explicit `false` is the point —
 * "do not exclude", not "unspecified".
 */
export function useAllCategories(options?: { enabled?: boolean }) {
  return useCategories(undefined, false, undefined, options);
}

export interface ScopedCategories {
  /** Every category the organization has — what naming a row needs. */
  all: CategoryDTO[] | undefined;
  /** The categories a general screen may offer as a filter. */
  scoped: CategoryDTO[] | undefined;
  /** Why `scoped` is still missing, once the lookup has failed — a screen
   *  that acts on the list must not read the gap as "no categories". */
  error: unknown;
  refetch: () => void;
}

/**
 * The two answers a general (non-module) screen needs about categories.
 *
 * The twin of `useLocationOffer`, and for the same reason: the organization
 * policy that keeps module-owned rows off the general lists has to govern
 * what a screen *offers* as well as what it shows. The product list applied
 * it to its rows and to its location filter but not to its category filter,
 * so the picker went on listing the equipment categories whose rows the list
 * had just hidden — every one of them a filter that narrows to nothing.
 *
 * `keepId` keeps one category in `scoped` regardless of its context, so a
 * filter already carried in the URL does not silently clear itself.
 */
export function useScopedCategories(keepId?: string | null): ScopedCategories {
  const excludeModuleContexts = !useShowModuleData();
  const allQuery = useAllCategories();
  const all = allQuery.data;
  const scopedQuery = useCategories(
    undefined,
    excludeModuleContexts,
    undefined,
    // With the policy off both queries would return the same list; asking
    // twice for it is a request nobody reads.
    { enabled: excludeModuleContexts },
  );
  const scopedData = scopedQuery.data;
  const failing = excludeModuleContexts ? scopedQuery : allQuery;
  const lookup = {
    error: failing.error,
    refetch: () => void failing.refetch(),
  };

  if (!excludeModuleContexts) return { all, scoped: all, ...lookup };
  if (!scopedData) return { all, scoped: undefined, ...lookup };
  if (!keepId || scopedData.some((c) => c.id === keepId))
    return { all, scoped: scopedData, ...lookup };

  const kept = all?.find((c) => c.id === keepId);
  return {
    all,
    scoped: kept ? [...scopedData, kept] : scopedData,
    ...lookup,
  };
}

/**
 * How many categories the module-data policy keeps off a general list.
 *
 * The twin of `useHiddenItemCount`: an empty *filtered* answer can mean
 * "nothing is here" or "kept out by the policy", and zero cannot tell — and
 * a *populated* list hides the same fact behind its own rows. One unfiltered
 * probe answers it; it runs beside the list for as long as the reader has
 * not narrowed the list themselves, and the counter is the difference
 * between what exists and what this list shows.
 */
export function useHiddenCategoryCount(
  excludeModuleContexts: boolean,
  isLoading: boolean,
  listLength: number | undefined,
  filtersActive: boolean,
): {
  count: number;
  isError: boolean;
  error: unknown;
  refetch: () => void;
} {
  const shouldProbe = excludeModuleContexts && !isLoading && !filtersActive;
  const { data, isError, error, refetch } = useCategories(true, false, true, {
    enabled: shouldProbe,
  });
  // While the reader narrows the list themselves the counter steps aside:
  // a stale probe answer must not speak over the filtering they are doing.
  if (!shouldProbe)
    return { count: 0, isError: false, error: null, refetch: () => {} };
  const unfilteredCount = data?.length ?? 0;
  // A probe that failed knows nothing, which is not "nothing is hidden": the
  // caller says so instead of showing a counter of zero.
  return {
    count: Math.max(unfilteredCount - (listLength ?? 0), 0),
    isError,
    error,
    refetch: () => void refetch(),
  };
}

export function useCreateCategory() {
  return useAppMutation(
    (data: Partial<CategoryDTO>) => categoriesApi.create(data),
    (qc) => {
      invalidation.categories(qc);
    },
    // surface duplicate/validation errors instead of failing silently.
    // extractApiError returns the server message (e.g. duplicate name) when
    // present; this fallback only shows if extraction fails.
    { errorFallback: "Failed to create category" },
  );
}

export function useUpdateCategory() {
  return useAppMutation(
    ({ id, data }: { id: string; data: Partial<CategoryDTO> }) =>
      categoriesApi.update(id, data),
    (qc) => {
      invalidation.categories(qc);
    },
  );
}

export function useRenameCategoryGroup() {
  return useAppMutation(
    ({
      currentName,
      newName,
      categoryIds,
    }: {
      currentName: string;
      newName: string | null;
      categoryIds?: string[];
    }) => categoriesApi.renameGroup(currentName, newName, categoryIds),
    (qc) => {
      invalidation.categories(qc);
    },
  );
}

export function useDeleteCategory() {
  return useAppMutation(
    (id: string) => categoriesApi.delete(id),
    (qc) => {
      invalidation.categories(qc);
    },
  );
}
