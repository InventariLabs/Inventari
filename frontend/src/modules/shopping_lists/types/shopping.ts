import type { components } from "@/types/api-generated";
import type { WithServerDefaults } from "@/types/request";
// Shopping list types.

export type ShoppingList = components["schemas"]["ShoppingList"];

export type ShoppingListItem = components["schemas"]["ShoppingListItem"];

export type ShoppingListWithItems =
  components["schemas"]["ShoppingListWithItems"];

export type ShoppingListItemCreate =
  components["schemas"]["ShoppingListItemCreate"];

/** What a caller sends: an unsaid priority or source is the server's default. */
export type ShoppingListItemInput = WithServerDefaults<
  ShoppingListItemCreate,
  "priority" | "source"
>;

/** One proposal the suggestion endpoints return. */
export type SuggestedItem = components["schemas"]["ShoppingSuggestionSchema"];

export type ShoppingSuggestionResponse =
  components["schemas"]["ShoppingSuggestionResponse"];

/** What the app would propose buying. Deliberately carries no `added`:
 *  a preview adds nothing, and reporting a zero there would be the same
 *  shape of untruth as the empty list this preview exists to stop
 *  creating. */
export type ShoppingSuggestionPreview =
  components["schemas"]["ShoppingSuggestionPreview"];

export type ConvertToPOResponse = components["schemas"]["ConvertToPOResponse"];

/**
 * The structured parts of a generated note, as the backend writes them. The
 * contract types `note_data` as a free map, so the card reads it through this
 * view instead of through `unknown`.
 */
export interface ShoppingNoteData {
  needed_by?: string;
  check_stock?: {
    available_qty: number | string;
    available_uom_id: string | null;
    required_qty: number | string;
    required_uom_id: string | null;
  };
  matched_by_name?: string;
  /** The recipe whose missing goods the line is; rendered in the reader's language. */
  for_recipe?: string;
  /** The number of the purchase order the line was converted into. */
  converted_to_po?: string;
}
