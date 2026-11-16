import { api } from "@/lib/api/client";
import type {
  LabelFacts,
  LabelFactsUpdate,
  RecipeLabel,
} from "@/modules/maker/types/maker";

/**
 * A product's label: what its card says (the name it goes under in an
 * ingredient list, its allergens, what it may contain) and what a recipe
 * computes from its ingredients' cards.
 */
export const labellingApi = {
  facts: async (templateId: string): Promise<LabelFacts> => {
    const response = await api.get<LabelFacts>(
      `/maker/labelling/products/${templateId}`,
    );
    return response.data;
  },

  setFacts: async (
    templateId: string,
    facts: LabelFactsUpdate,
  ): Promise<LabelFacts> => {
    const response = await api.put<LabelFacts>(
      `/maker/labelling/products/${templateId}`,
      facts,
    );
    return response.data;
  },

  recipeLabel: async (recipeId: string): Promise<RecipeLabel> => {
    const response = await api.get<RecipeLabel>(
      `/maker/labelling/recipes/${recipeId}`,
    );
    return response.data;
  },
};
