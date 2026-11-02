import { api, getEveryPage } from "@/lib/api/client";
import type { components } from "@/types/api-generated";
import type {
  ShoppingList,
  ShoppingListWithItems,
  ShoppingListItem,
  ShoppingListItemInput,
  ShoppingSuggestionPreview,
  ShoppingSuggestionResponse,
  ConvertToPOResponse,
} from "@/modules/shopping_lists/types/shopping";

/** What the "from recipes" sheet shows of one recipe. */
export type RecipeOption = Pick<
  components["schemas"]["RecipeList"],
  "id" | "name" | "image_url" | "tags"
>;

export const shoppingListsApi = {
  // ── Recipes, as the "from recipes" sheet reads them ──
  // The recipes module's HTTP routes: that module prices a recipe against
  // stock and owns the route that does it. Its files are not this module's
  // to import — recipes may be off, and an import cannot be.
  listRecipes: async (params: {
    search?: string;
    limit: number;
  }): Promise<{ items: RecipeOption[]; total: number }> => {
    const response = await api.get<{ items: RecipeOption[]; total: number }>(
      "/recipes",
      { params },
    );
    return response.data;
  },

  addFromRecipes: async (data: {
    recipe_ids: string[];
    shopping_list_id: string;
  }): Promise<{ added_count: number }> => {
    const response = await api.post<{ added_count: number }>(
      "/recipes/shopping-list/add-from-recipes",
      data,
    );
    return response.data;
  },

  getAll: async (activeOnly: boolean = true): Promise<ShoppingList[]> => {
    return getEveryPage<ShoppingList>("/shopping-lists", {
      active_only: activeOnly,
    });
  },

  getById: async (id: string): Promise<ShoppingListWithItems> => {
    const response = await api.get<ShoppingListWithItems>(
      `/shopping-lists/${id}`,
    );
    return response.data;
  },

  create: async (data: { name?: string }): Promise<ShoppingList> => {
    const response = await api.post<ShoppingList>("/shopping-lists", data);
    return response.data;
  },

  update: async (
    id: string,
    data: { name?: string },
  ): Promise<ShoppingList> => {
    const response = await api.put<ShoppingList>(`/shopping-lists/${id}`, data);
    return response.data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/shopping-lists/${id}`);
  },

  addItem: async (
    listId: string,
    data: ShoppingListItemInput,
  ): Promise<ShoppingListItem> => {
    const response = await api.post<ShoppingListItem>(
      `/shopping-lists/${listId}/items`,
      data,
    );
    return response.data;
  },

  addItemsBulk: async (
    listId: string,
    items: ShoppingListItemInput[],
  ): Promise<ShoppingListItem[]> => {
    const response = await api.post<ShoppingListItem[]>(
      `/shopping-lists/${listId}/items/bulk`,
      items,
    );
    return response.data;
  },

  toggleItemPurchased: async (
    listId: string,
    itemId: string,
  ): Promise<ShoppingListItem> => {
    const response = await api.patch<ShoppingListItem>(
      `/shopping-lists/${listId}/items/${itemId}/purchase`,
    );
    return response.data;
  },

  toggleItemUnpurchased: async (
    listId: string,
    itemId: string,
  ): Promise<ShoppingListItem> => {
    const response = await api.patch<ShoppingListItem>(
      `/shopping-lists/${listId}/items/${itemId}/unpurchase`,
    );
    return response.data;
  },

  deleteItem: async (listId: string, itemId: string): Promise<void> => {
    await api.delete(`/shopping-lists/${listId}/items/${itemId}`);
  },

  clearPurchasedItems: async (listId: string): Promise<void> => {
    await api.delete(`/shopping-lists/${listId}/items/purchased`);
  },

  generateSuggestions: async (
    listId: string,
  ): Promise<ShoppingSuggestionResponse> => {
    const response = await api.post<ShoppingSuggestionResponse>(
      `/shopping-lists/${listId}/suggestions/generate`,
    );
    return response.data;
  },

  /** What the app would propose buying, with no list to propose it onto.
   *  The dashboard used to create an empty list simply to have an id for
   *  this read, and Cancel did not take it back. */
  previewSuggestions: async (params?: {
    include_low_stock?: boolean;
    include_frequent?: boolean;
    include_expiring?: boolean;
  }): Promise<ShoppingSuggestionPreview> => {
    const response = await api.get<ShoppingSuggestionPreview>(
      `/shopping-lists/suggestions`,
      { params },
    );
    return response.data;
  },

  /** The active list to put things on, making one only if there is none.
   *  Nothing calls this while a reader is merely looking: a preview
   *  creates nothing, and this runs when they have chosen to buy. */
  ensureActiveList: async (): Promise<string> => {
    const active = await shoppingListsApi.getAll(true);
    if (active[0]?.id) return active[0].id;
    const created = await shoppingListsApi.create({});
    return created.id;
  },

  convertToPo: async (
    listId: string,
    supplierId?: string,
  ): Promise<ConvertToPOResponse> => {
    const response = await api.post<ConvertToPOResponse>(
      `/shopping-lists/${listId}/convert-to-po`,
      { supplier_id: supplierId ?? null },
    );
    return response.data;
  },
};
