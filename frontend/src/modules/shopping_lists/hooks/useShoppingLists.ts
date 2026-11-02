import { useQuery, useQueries } from "@tanstack/react-query";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { shoppingListsApi } from "@/modules/shopping_lists/api/shopping-lists";
import { invalidation } from "@/lib/api/invalidation";
import { queryKeys } from "@/hooks/queries/keys";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import { useModules } from "@/contexts/ModulesContext";
import type {
  ShoppingList,
  ShoppingListWithItems,
} from "@/modules/shopping_lists/types/shopping";

export function useActiveShoppingList() {
  return useModuleQuery<ShoppingListWithItems | null>("shopping_lists", {
    queryKey: queryKeys.shoppingLists.active,
    queryFn: async () => {
      const lists = await shoppingListsApi.getAll(true);
      if (lists.length === 0) return null;
      return await shoppingListsApi.getById(lists[0].id);
    },
    staleTime: 30000,
  });
}

/**
 * The recipes the "from recipes" sheet offers, under the key the recipes
 * module's own list uses for the same question, so the two share a cache
 * entry.
 */
export function useRecipeOptions(params: { search?: string; limit: number }) {
  return useModuleQuery("recipes", {
    queryKey: queryKeys.recipes.all(params),
    queryFn: () => shoppingListsApi.listRecipes(params),
  });
}

export function useQuickAddToShoppingList() {
  return useAppMutation(
    async (item: {
      name: string;
      quantity?: number;
      unit?: string;
      item_id?: string;
    }) => {
      const lists = await shoppingListsApi.getAll(true);
      let listId: string;
      if (lists.length === 0) {
        const newList = await shoppingListsApi.create({
          name: "Shopping List",
        });
        listId = newList.id;
      } else {
        listId = lists[0].id;
      }
      return shoppingListsApi.addItem(listId, {
        name: item.name,
        quantity: item.quantity ?? 1,
        item_id: item.item_id,
      });
    },
    (qc) => {
      invalidation.shoppingLists(qc);
    },
  );
}

/**
 * What the app would propose buying, asked without a list.
 *
 * The dashboard's button used to reach this answer through a list it had
 * just created — the only route to it was addressed by `list_id` — so
 * opening a preview left an empty active list nobody had asked for, and
 * Cancel did not take it back.
 *
 * `sources` is here because the button hangs on the tile counting
 * shortages: the engine returns every source it knows unless it is asked
 * otherwise, which is how a low-stock button opened a screenful of
 * expired products.
 */
export function useShoppingSuggestionsPreview(
  enabled: boolean,
  sources?: {
    include_low_stock?: boolean;
    include_frequent?: boolean;
    include_expiring?: boolean;
  },
) {
  return useQuery({
    queryKey: queryKeys.shoppingLists.suggestionsPreview(sources),
    queryFn: () => shoppingListsApi.previewSuggestions(sources),
    enabled,
  });
}

/**
 * Adds to a list named at the moment of adding, not at the moment of
 * looking. The preview above creates nothing, so which list the rows land
 * on is only known once somebody has decided to buy something.
 */
export function useAddShoppingItemsToAList() {
  return useAppMutation(
    ({
      listId,
      items,
    }: {
      listId: string;
      items: Parameters<typeof shoppingListsApi.addItemsBulk>[1];
    }) => shoppingListsApi.addItemsBulk(listId, items),
    (qc) => {
      invalidation.shoppingLists(qc);
    },
  );
}

export function useConvertToPO(listId: string) {
  return useAppMutation(
    (supplierId?: string) => shoppingListsApi.convertToPo(listId, supplierId),
    (qc) => {
      invalidation.shoppingLists(qc);
    },
  );
}

export function useShoppingLists() {
  return useModuleQuery<ShoppingList[]>("shopping_lists", {
    queryKey: queryKeys.shoppingLists.all,
    queryFn: () => shoppingListsApi.getAll(),
  });
}

export function useShoppingListDetail(id: string | undefined) {
  return useModuleQuery<ShoppingListWithItems>("shopping_lists", {
    queryKey: queryKeys.shoppingLists.detail(id!),
    queryFn: () => shoppingListsApi.getById(id!),
    extraEnabled: !!id,
  });
}

/** How many of a list's things fit on its card before the "+N". */
const PREVIEW_NAMES = 3;

export interface ShoppingListPreview {
  total: number;
  purchased: number;
  /** The first few things on the list, in the order they were added. */
  names: string[];
}

export function useShoppingListStats(lists: ShoppingList[]) {
  const { isModuleEnabled } = useModules();
  const results = useQueries({
    queries: lists.map((list) => ({
      queryKey: queryKeys.shoppingLists.detail(list.id),
      queryFn: () => shoppingListsApi.getById(list.id),
      enabled: isModuleEnabled("shopping_lists"),
    })),
  });

  // The names come from the same answer the counts do. The card used to draw
  // four identical box glyphs from `total` alone, so six lists of six things
  // each looked like the same six things.
  const stats: Record<string, ShoppingListPreview> = {};
  results.forEach((result, i) => {
    if (result.data) {
      const list = lists[i];
      const items = result.data.items ?? [];
      stats[list.id] = {
        total: items.length,
        purchased: items.filter((item) => item.is_purchased).length,
        names: items.slice(0, PREVIEW_NAMES).map((item) => item.name),
      };
    }
  });
  return stats;
}

export function useDeleteShoppingList() {
  return useAppMutation(
    (id: string) => shoppingListsApi.delete(id),
    (qc) => {
      invalidation.shoppingLists(qc);
    },
  );
}

export function useUpdateShoppingList() {
  return useAppMutation(
    ({ id, name }: { id: string; name: string }) =>
      shoppingListsApi.update(id, { name }),
    (qc) => {
      invalidation.shoppingLists(qc);
    },
  );
}

export function useToggleShoppingItem(listId: string) {
  return useAppMutation(
    ({ itemId, currentStatus }: { itemId: string; currentStatus: boolean }) =>
      currentStatus
        ? shoppingListsApi.toggleItemUnpurchased(listId, itemId)
        : shoppingListsApi.toggleItemPurchased(listId, itemId),
    (qc) => {
      invalidation.shoppingLists(qc);
    },
  );
}

export function useClearPurchasedItems(listId: string) {
  return useAppMutation(
    () => shoppingListsApi.clearPurchasedItems(listId),
    (qc) => {
      invalidation.shoppingLists(qc);
    },
  );
}

export function useDeleteShoppingItem(listId: string) {
  return useAppMutation(
    (itemId: string) => shoppingListsApi.deleteItem(listId, itemId),
    (qc) => {
      invalidation.shoppingLists(qc);
    },
  );
}
