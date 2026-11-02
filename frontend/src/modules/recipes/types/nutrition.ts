import type { components } from "@/types/api-generated";

export type RecipeNutrition = components["schemas"]["RecipeNutrition"];

export type CookingHistoryItem = components["schemas"]["CookingHistoryItem"];

export type RecipeCost = components["schemas"]["RecipeCost"];

export type RecipeTagItem = components["schemas"]["RecipeTagItem"];

export type TagMergeRequest = components["schemas"]["TagMergeRequest"];

export type TagMergeResponse = components["schemas"]["TagMergeResponse"];

/**
 * A recipe import request. The contract types `format` a plain string; the
 * import dialog offers the two the server documents, and the server refuses
 * the rest — the union lived here twice otherwise.
 */
export type RecipeImportRequest = components["schemas"]["RecipeImportRequest"];
export type PreviewIngredient = components["schemas"]["PreviewIngredient"];

/** The parsed preview behind the import confirmation. Not a schema under
 *  another name: the backend answers this shape inline, never as a named
 *  model, so there is nothing to alias. */
export interface RecipeImportPreview {
  name: string;
  description: string | null;
  instructions: string | null;
  servings: number;
  prep_time_minutes: number | null;
  image_source_url: string | null;
  source_url: string | null;
  tags: string[];
  ingredients: PreviewIngredient[];
  parse_warning: string | null;
}
