import { api, getEveryPage } from "@/lib/api/client";
import type {
  BulkLinkIngredientsRequest,
  BulkLinkIngredientsResponse,
  IngredientMatchProposalsResponse,
  UnlinkedIngredient,
} from "@/modules/recipes/types/linking";

export const recipesLinkingApi = {
  /** Every ingredient in the organization no recipe has linked yet. */
  listUnlinkedIngredients: (): Promise<UnlinkedIngredient[]> =>
    getEveryPage<UnlinkedIngredient>("/recipes/ingredients/unlinked"),

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
