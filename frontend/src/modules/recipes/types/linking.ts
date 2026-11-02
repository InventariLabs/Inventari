// Types of the global ingredient-linking screen.
//
// Aliases to the generated wire contract, not mirrors: the whole shape is a
// copy of the backend schemas, so there is nothing for a hand-written
// interface to add (frontend/AGENTS.md §1, state 1).
import type { components } from "@/types/api-generated";

export type UnlinkedIngredient = components["schemas"]["UnlinkedIngredient"];
export type IngredientMatchProposal =
  components["schemas"]["IngredientMatchProposal"];
export type IngredientMatchProposalsResponse =
  components["schemas"]["IngredientMatchProposalsResponse"];
export type BulkLinkIngredientsRequest =
  components["schemas"]["BulkLinkIngredientsRequest"];
export type BulkLinkIngredientsResponse =
  components["schemas"]["BulkLinkIngredientsResponse"];
