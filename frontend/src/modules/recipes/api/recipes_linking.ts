import { api, getEveryPage } from "@/lib/api/client";
import type {
  BulkLinkIngredientsRequest,
  BulkLinkIngredientsResponse,
  IngredientMatchProposalsResponse,
  UnlinkedBacklog,
  UnlinkedIngredient,
  UnlinkedIngredientsPage,
} from "@/modules/recipes/types/linking";

export const recipesLinkingApi = {
  /**
   * Every ingredient in the organization no recipe has linked yet, and whether
   * the recipes hold any ingredient at all — an empty backlog means "all
   * linked" only when they do.
   */
  listUnlinkedIngredients: async (): Promise<UnlinkedBacklog> => {
    const items = await getEveryPage<UnlinkedIngredient>(
      "/recipes/ingredients/unlinked",
    );
    if (items.length > 0) return { items, hasIngredients: true };
    const { data } = await api.get<UnlinkedIngredientsPage>(
      "/recipes/ingredients/unlinked",
      { params: { limit: 1 } },
    );
    return { items, hasIngredients: data.ingredient_total > 0 };
  },

  /** Ask the matcher for proposals; none of them is written. */
  suggestIngredientMatches:
    async (): Promise<IngredientMatchProposalsResponse> => {
      const response = await api.post<IngredientMatchProposalsResponse>(
        "/recipes/ingredients/match-proposals",
      );
      return response.data;
    },

  /** Apply the approved subset in one write. */
  bulkLinkIngredients: async (
    links: BulkLinkIngredientsRequest["links"],
  ): Promise<BulkLinkIngredientsResponse> => {
    const response = await api.post<BulkLinkIngredientsResponse>(
      "/recipes/ingredients/link-templates",
      { links },
    );
    return response.data;
  },
};
