import { useAppMutation } from "@/lib/api/mutationFactory";
import { invalidation } from "@/lib/api/invalidation";
import { queryKeys } from "@/hooks/queries/keys";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import { recipesApi } from "@/modules/recipes/api/recipes";
import type { BulkLinkIngredientsRequest } from "@/modules/recipes/types/linking";

/** The organization's whole unlinked-ingredient backlog, one query. */
export function useUnlinkedIngredients() {
  return useModuleQuery("recipes", {
    queryKey: queryKeys.recipes.unlinkedIngredients,
    queryFn: () => recipesApi.listUnlinkedIngredients(),
  });
}

/**
 * LLM match proposals for the backlog.
 *
 * Nothing is stored server-side, so there is no cache to refresh: the
 * proposals are the mutation's result and live in the page.
 */
export function useSuggestIngredientMatches() {
  return useAppMutation(
    () => recipesApi.suggestIngredientMatches(),
    () => {},
  );
}

/** Apply the approved proposals; the whole recipe namespace is stale after. */
export function useBulkLinkIngredients() {
  return useAppMutation(
    (links: BulkLinkIngredientsRequest["links"]) =>
      recipesApi.bulkLinkIngredients(links),
    (qc) => {
      invalidation.recipes(qc);
    },
  );
}
