import type { components } from "@/types/api-generated";
import type { WithServerDefaults } from "@/types/request";

/** The slots a plan's day is divided into — the schema's own union. */
export type MealSlot = components["schemas"]["MealSlot"];

/** One planned meal. A mirror of `MealPlanEntrySchema` under the shorter
 *  name; the wire types `notes` and `picking_session_id` optional-nullable. */
export type MealPlanEntry = components["schemas"]["MealPlanEntrySchema"];

/** A meal plan, as `GET /meal-plans/:id` answers. A mirror of
 *  `MealPlanSchema` under the shorter name. */
export type MealPlan = components["schemas"]["MealPlanSchema"];

export type MealPlanListItem = components["schemas"]["MealPlanListItem"];

export type MealPlanCreate = components["schemas"]["MealPlanCreate"];

export type MealPlanUpdate = components["schemas"]["MealPlanUpdate"];

/** What a caller sends: the conflict flag it leaves out is the server's default (keep the entries, answer 409). */
export type MealPlanUpdateInput = WithServerDefaults<
  MealPlanUpdate,
  "remove_conflicting_entries"
>;

export type MealPlanEntryCreate = components["schemas"]["MealPlanEntryCreate"];

export type MealPlanEntryUpdate = components["schemas"]["MealPlanEntryUpdate"];

export type CopyPlanRequest = components["schemas"]["CopyPlanRequest"];

export type CopyPlanResponse = components["schemas"]["CopyPlanResponse"];

export type SuggestedRecipe = components["schemas"]["SuggestedRecipe"];

/** One line the shopping-list generation produced. A mirror of
 *  `_GeneratedItem` under a name without the underscore. */
export type GeneratedItem = components["schemas"]["_GeneratedItem"];

export type ShoppingListGenerationResult =
  components["schemas"]["ShoppingListGenerationResult"];

/** One excluded product, as the exclusions list answers. A mirror of
 *  `ShoppingExclusionSchema` under the shorter name. */
export type ShoppingExclusion =
  components["schemas"]["ShoppingExclusionSchema"];

export type ShoppingExclusionCreate =
  components["schemas"]["ShoppingExclusionCreate"];
