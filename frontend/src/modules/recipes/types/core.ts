import type { components } from "@/types/api-generated";
import type { WithServerDefaults } from "@/types/request";

/**
 * One recipe line, as the recipe detail answers. Taken from the schema
 * rather than retyped: the hand-written copy typed `quantity`,
 * `calories_kcal_per_100g`, `original_quantity` and `price` as numbers,
 * where the wire carries Decimals as strings (TECHNICAL_DECISIONS §18) —
 * the same drift that made two plus three read `2.0003` on the item card.
 * The picking-suggestion quantities (`OpenedSuggestion`,
 * `DisambiguationCandidate`) stay numbers on purpose — §18's exception.
 */
export type RecipeIngredient = components["schemas"]["RecipeIngredient"];

export type RecipeIngredientCreate =
  components["schemas"]["RecipeIngredientCreate"];

/** A recipe, as `GET /recipes/:id` answers. */
export type Recipe = components["schemas"]["Recipe"];

/** The recipe list row with the availability counts the list computes. */
export type RecipeList = components["schemas"]["RecipeList"];

/** A create payload. The schema's own name is mangled in the contract
 *  (`app__modules__recipes___schemas_recipe__RecipeCreate`); the alias
 *  points at it all the same. */
export type RecipeCreate =
  components["schemas"]["app__modules__recipes___schemas_recipe__RecipeCreate"];

/** An ingredient as a caller sends it: the picking flag it leaves out is the server's default. */
export type RecipeIngredientCreateInput = WithServerDefaults<
  RecipeIngredientCreate,
  "picking_skip"
>;

/** A recipe as a caller sends it: an unsaid favourite flag is the server's default, and so is an ingredient's picking flag. */
export type RecipeCreateInput = Omit<
  WithServerDefaults<RecipeCreate, "is_favorite">,
  "ingredients"
> & { ingredients?: RecipeIngredientCreateInput[] | null };

export type RecipeUpdate =
  components["schemas"]["app__modules__recipes___schemas_recipe__RecipeUpdate"];

/**
 * One ingredient's availability verdict. Taken from the schema rather than
 * retyped: the hand-written copy narrowed `status` to the six values the
 * food recipes ship with and `match_type` to two — the same narrowing that
 * broke `Category.category_type` for every other vertical.
 */
export type IngredientAvailability =
  components["schemas"]["IngredientAvailability"];

export type RecipeAvailability = components["schemas"]["RecipeAvailability"];

/** One line of an open picking session. A mirror of `PickingItemSchema`
 *  under the shorter name — the wire narrows `status` to a string. */
export type PickingItem = components["schemas"]["PickingItemSchema"];

export type PickingStartResponse =
  components["schemas"]["PickingStartResponse"];

/**
 * What scanning a code during picking answers. The contract types `status`
 * a plain string; screens read the values the server documents in the
 * backend Literal, so a switch over the response stays correct by
 * construction of the server, not by a frontend copy of its union.
 */
export type PickingScanResponse = components["schemas"]["PickingScanResponse"];

export type UndoPickResponse = components["schemas"]["UndoPickResponse"];

/** A collection in the sidebar tree. A mirror of `RecipeCollectionSchema`
 *  under the shorter name. */
export type RecipeCollection = components["schemas"]["RecipeCollectionSchema"];

export type RecipeCollectionCreate =
  components["schemas"]["RecipeCollectionCreate"];
