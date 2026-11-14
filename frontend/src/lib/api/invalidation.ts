import type { Query, QueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/hooks/queries/keys";

/**
 * Centralised cache invalidation helpers.
 *
 * Use these instead of scattering raw `queryClient.invalidateQueries` calls
 * to ensure consistent invalidation across mutations.
 *
 * Every `queryKey:` property and every key given to `invalidateQueries` is built
 * from `queryKeys`; `scripts/check-invalidation-keys.mjs` fails on a literal
 * array, on a key held in a variable or local registry, and on an invalidated
 * root no registered key starts with. Keys passed positionally to
 * `setQueryData` / `getQueryData` / `fetchQuery` are not read. Files that still hold a local registry are
 * listed, with an owner and an expiry, in `invalidation-keys-baseline.json`.
 *
 * Stats note: the `["stats"]` prefix covers `["stats", "overview"]` and its
 * siblings. A second, flat `["stats-overview"]` key used to be invalidated
 * beside it "since some components still use the old key directly" — none
 * did; nothing ever read it, so three invalidations were addressed to a
 * cache entry that did not exist.
 */
export const invalidation = {
  /** Invalidate the movement ledger — the answer to "what just happened to
   * stock?". Every writer of moves funnels through one of the helpers below
   * that also calls this: documents (receipts, issues, transfers, corrections,
   * returns), quick item ops (consume, discard, move, quantity, import),
   * stock takes (count corrections) and production. Without it the ledger's
   * 30 s staleness read as "this document moved nothing" seconds after the
   * document moved ten units. */
  stockMoves(queryClient: QueryClient) {
    queryClient.invalidateQueries({ queryKey: queryKeys.stockMoves.all });
    // Three families of recipe answers are measured on the shelf. The
    // filtered lists carry stock counts (their second key part is the params
    // object); "what can I cook" is `["recipes", "available", ...]`; an open
    // card's availability is `["recipes", "detail", id, "availability", ...]`.
    // Only a pick used to refresh the last two, so a receipt, a product edit,
    // a stock take or a production run left the old verdict on screen for the
    // whole staleTime. The rest of the detail family (history, cost,
    // nutrition) does not depend on stock and is left alone.
    queryClient.invalidateQueries({
      queryKey: queryKeys.recipes.all(),
      predicate: (query) =>
        typeof query.queryKey[1] !== "string" ||
        query.queryKey[1] === "available" ||
        query.queryKey[3] === "availability",
    });
  },

  /** Invalidate item-related caches, optionally scoped to storage or detail. */
  items(queryClient: QueryClient, storageId?: string) {
    queryClient.invalidateQueries({ queryKey: queryKeys.items.all });
    queryClient.invalidateQueries({ queryKey: queryKeys.items.archived });
    queryClient.invalidateQueries({ queryKey: queryKeys.stats.overview });
    this.stockMoves(queryClient);
    // A created template changes "is the catalog empty" — without this the
    // pricelist/reorder-rule CTAs stay disabled until staleTime expires
    // ( follow-up).
    queryClient.invalidateQueries({
      queryKey: queryKeys.productTemplates.count,
    });
    // The products list of a location is a separate key, and an item mutation
    // usually cannot say which location it touched — an edit may have moved
    // the product from one shelf to another, which makes two of them wrong.
    // Without this the list and the filter chips above it kept showing the
    // state from before the save for the full five-minute `staleTime`, which
    // reads exactly like a save that did not work.
    queryClient.invalidateQueries({
      queryKey: storageId
        ? queryKeys.items.storageItems(storageId)
        : queryKeys.items.allStorageItems,
    });
  },

  /** Invalidate all storage-related caches. */
  storages(queryClient: QueryClient, storageId?: string) {
    queryClient.invalidateQueries({ queryKey: queryKeys.storages.all });
    queryClient.invalidateQueries({ queryKey: queryKeys.storages.tree });
    queryClient.invalidateQueries({ queryKey: queryKeys.items.all });
    queryClient.invalidateQueries({ queryKey: queryKeys.stats.overview });
    if (storageId) {
      queryClient.invalidateQueries({
        queryKey: queryKeys.storages.detail(storageId),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.items.storageItems(storageId),
      });
    }
  },

  /** After a location is deleted: the caches `storages()` refreshes, except
   * the ones that name the deleted location. The screen that deleted it is
   * still on it when the refresh fires — it leaves on the mutation's own
   * success — and a refresh of its card, path or branch asks the server for
   * a place that no longer exists and logs a 404. */
  storageDeleted(queryClient: QueryClient, storageId: string) {
    const namesOther = (query: Query) => !query.queryKey.includes(storageId);
    queryClient.invalidateQueries({
      queryKey: queryKeys.storages.all,
      predicate: namesOther,
    });
    queryClient.invalidateQueries({
      queryKey: queryKeys.storages.tree,
      predicate: namesOther,
    });
    queryClient.invalidateQueries({ queryKey: queryKeys.items.all });
    queryClient.invalidateQueries({ queryKey: queryKeys.stats.overview });
  },

  /** Invalidate stats and overview. */
  stats(queryClient: QueryClient) {
    queryClient.invalidateQueries({ queryKey: queryKeys.stats.overview });
  },

  /** Invalidate shopping list caches. */
  shoppingLists(queryClient: QueryClient) {
    queryClient.invalidateQueries({ queryKey: queryKeys.shoppingLists.all });
    queryClient.invalidateQueries({ queryKey: queryKeys.shoppingLists.active });
    // Writing to a list changes what the engine still proposes — an added
    // item becomes a duplicate the next preview filters out. Without this
    // the dashboard's door outlived the run it was offering and stood open
    // over an empty modal.
    queryClient.invalidateQueries({
      queryKey: queryKeys.shoppingLists.suggestionsAll,
    });
  },

  /** Invalidate recipe caches. */
  recipes(queryClient: QueryClient, recipeId?: string) {
    queryClient.invalidateQueries({ queryKey: queryKeys.recipes.all() });
    // The tags key lives outside the ["recipes"] prefix — without this,
    // newly created tags never show up in the filter bar.
    queryClient.invalidateQueries({ queryKey: queryKeys.recipes.tags });
    if (recipeId) {
      queryClient.invalidateQueries({
        queryKey: queryKeys.recipes.detail(recipeId),
      });
    }
  },

  /** Invalidate the availability answers the shopping door reads.
   *
   * Changing the "Always at home" exclusions re-decides which missing
   * ingredients still need buying; without this the "Add missing" button
   * on an open recipe stayed live (or dead) until a manual refresh.
   */
  recipeAvailability(queryClient: QueryClient) {
    queryClient.invalidateQueries({
      predicate: (query) =>
        query.queryKey[0] === "recipes" && query.queryKey[3] === "availability",
    });
  },

  /** Invalidate label caches. */
  labels(queryClient: QueryClient) {
    queryClient.invalidateQueries({ queryKey: queryKeys.labels.all });
  },

  /** Invalidate webhook caches. */
  webhooks(queryClient: QueryClient) {
    queryClient.invalidateQueries({ queryKey: queryKeys.webhooks.all });
  },

  /** Invalidate organization caches. */
  organization(queryClient: QueryClient) {
    queryClient.invalidateQueries({ queryKey: queryKeys.organization.detail });
    queryClient.invalidateQueries({ queryKey: queryKeys.organization.members });
    // The country is part of the organization, and the rate offer and the
    // partner tax-ID rule Warehouse settings show are read from it.
    queryClient.invalidateQueries({
      queryKey: queryKeys.documents.taxRatesCountry,
    });
  },

  /**
   * Who holds which right has changed — a member's role, a member gone, a
   * role's permissions. Every answer the server computed from those rights
   * goes stale with them: the roles, and the approval verdicts ("a stage
   * nobody can decide", a request that cannot be decided), which sat under a
   * five-minute staleTime and kept the old answer until a reload.
   *
   * `removedRoleId` — the role a delete has just taken away — is left out:
   * the members key sits under the roles prefix, and asking the role that no
   * longer exists for its members answered 400 behind the 204 that closed
   * the delete dialog.
   */
  rights(queryClient: QueryClient, removedRoleId?: string) {
    queryClient.invalidateQueries({
      queryKey: queryKeys.roles.all,
      // Anything under ["roles"] whose second element is the deleted role is
      // a question about it, and it is gone.
      predicate: removedRoleId
        ? (query) => query.queryKey[1] !== removedRoleId
        : undefined,
    });
    invalidation.approvals(queryClient);
  },

  /** Invalidate admin caches. */
  admin(queryClient: QueryClient) {
    queryClient.invalidateQueries({ queryKey: queryKeys.admin.all });
  },

  /** Invalidate notification caches. */
  notifications(queryClient: QueryClient) {
    queryClient.invalidateQueries({ queryKey: queryKeys.notifications.all });
  },

  /** Invalidate storage-type caches. */
  storageTypes(queryClient: QueryClient) {
    queryClient.invalidateQueries({ queryKey: queryKeys.storages.types });
  },

  /** Invalidate purchase order caches. */
  purchaseOrders(queryClient: QueryClient, poId?: string) {
    queryClient.invalidateQueries({ queryKey: queryKeys.purchaseOrders.all });
    if (poId) {
      queryClient.invalidateQueries({
        queryKey: queryKeys.purchaseOrders.detail(poId),
      });
    }
  },

  /** Invalidate equipment caches. */
  equipment(queryClient: QueryClient, itemId?: string) {
    queryClient.invalidateQueries({ queryKey: queryKeys.equipment.all });
    queryClient.invalidateQueries({ queryKey: queryKeys.equipment.dashboard });
    queryClient.invalidateQueries({ queryKey: queryKeys.equipment.models });
    queryClient.invalidateQueries({
      queryKey: queryKeys.equipment.maintenance.all,
    });
    queryClient.invalidateQueries({
      queryKey: queryKeys.equipment.campaigns.list,
    });
    queryClient.invalidateQueries({ queryKey: queryKeys.items.all });
    if (itemId) {
      queryClient.invalidateQueries({
        queryKey: queryKeys.equipment.assets.detail(itemId),
      });
    }
  },

  /** Invalidate document caches. */
  documents(queryClient: QueryClient, docId?: string) {
    queryClient.invalidateQueries({ queryKey: queryKeys.documents.all });
    // A document is a stock write. Receipts, issues, transfers, corrections
    // and returns all funnel through here, and each of them changes the
    // product list, the quants, the lots and the statistics — none of which
    // this helper used to touch. With the global five-minute staleTime and
    // no refetch on focus, the product list opened within five minutes of a
    // receipt showed the stock from before it. The stock screens had each
    // patched themselves with a 30-second staleTime, which is the same bug
    // found and treated three times locally instead of once here.
    this.items(queryClient);
    queryClient.invalidateQueries({ queryKey: queryKeys.stockQuants.all });
    queryClient.invalidateQueries({ queryKey: queryKeys.stockLots.all });
    // A receipt that names order lines moves what the order has received,
    // and an undone one moves it back. The order screen held its own copy
    // for five minutes and went on saying nothing had arrived.
    this.purchaseOrders(queryClient);
    if (docId) {
      queryClient.invalidateQueries({
        queryKey: queryKeys.documents.detail(docId),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.documents.approval(docId),
      });
    }
  },

  /** Invalidate inventory period caches. */
  inventoryPeriods(queryClient: QueryClient) {
    queryClient.invalidateQueries({ queryKey: queryKeys.documents.periods });
  },

  /** Invalidate putaway rule caches. */
  putawayRules(queryClient: QueryClient) {
    queryClient.invalidateQueries({
      queryKey: queryKeys.documents.putawayRules,
    });
  },

  /** Invalidate meal plan caches. */
  mealPlans(queryClient: QueryClient, planId?: string) {
    queryClient.invalidateQueries({ queryKey: queryKeys.mealPlans.all() });
    queryClient.invalidateQueries({
      queryKey: queryKeys.mealPlans.exclusions,
    });
    if (planId) {
      queryClient.invalidateQueries({
        queryKey: queryKeys.mealPlans.detail(planId),
      });
    }
  },

  /** Invalidate category caches. */
  categories(queryClient: QueryClient) {
    queryClient.invalidateQueries({ queryKey: queryKeys.categories.all });
  },

  /** Invalidate partner caches. */
  partners(queryClient: QueryClient) {
    queryClient.invalidateQueries({ queryKey: queryKeys.partners.all });
  },

  /** Invalidate template caches for a module. */
  templates(queryClient: QueryClient, module: string) {
    queryClient.invalidateQueries({
      queryKey: queryKeys.templates.list(module),
    });
  },

  /** Invalidate stock take caches. */
  stockTakes(queryClient: QueryClient, id?: string) {
    queryClient.invalidateQueries({
      queryKey: queryKeys.stockTakes.all,
    });
    this.stockMoves(queryClient);
    if (id) {
      queryClient.invalidateQueries({
        queryKey: queryKeys.stockTakes.detail(id),
      });
    }
  },

  /** Invalidate what a picking session moved.
   *
   * A scan takes stock off the shelf; an undo, a cancel and the walk the
   * finished screen runs to put it back or close it out all write the
   * shelves and the ledger the same way any other stock write does. The
   * picking hooks reached for the API directly and invalidated nothing, so
   * with the global five-minute staleTime and no refetch on focus an item
   * list, an item card, the ledger, the quants and lots or the recipe's
   * availability opened before the pick kept the shelf from before it for
   * as long as the reader stayed on it. */
  picking(queryClient: QueryClient, recipeId?: string) {
    this.items(queryClient);
    queryClient.invalidateQueries({ queryKey: queryKeys.stockQuants.all });
    queryClient.invalidateQueries({ queryKey: queryKeys.stockLots.all });
    if (recipeId) {
      // Availability is measured on the stock the pick just moved; the
      // parameterised key is reached through its prefix so every servings
      // value an open card read is refreshed, not only the one this call
      // happens to know.
      queryClient.invalidateQueries({
        queryKey: queryKeys.recipes.availabilityAll(recipeId),
      });
      // "What can I cook" is the same question asked of every recipe at
      // once, and a pick can flip who is cookable too.
      queryClient.invalidateQueries({
        queryKey: queryKeys.recipes.available(),
      });
      // The finished session is a new row (or a continued one) of the
      // recipe's cooking history; a panel opened before the cook would
      // otherwise keep listing the sessions from before it.
      queryClient.invalidateQueries({
        queryKey: queryKeys.recipes.history(recipeId),
      });
    }
  },

  /** Invalidate announcement caches (admin + active). */
  announcements(queryClient: QueryClient) {
    queryClient.invalidateQueries({ queryKey: queryKeys.admin.announcements });
    queryClient.invalidateQueries({
      queryKey: queryKeys.announcements.active,
    });
  },

  /** Invalidate approval caches. */
  approvals(queryClient: QueryClient) {
    // The whole namespace through its root: the request queue and the
    // workflow list both sit under `["approvals"]`, and naming them one by
    // one is how a third approvals key would go unrefreshed.
    queryClient.invalidateQueries({ queryKey: queryKeys.approvals.all });
    // the documents "Awaiting My Approval" queue renders the same
    // requests — refresh it after approve/reject so the card transitions to
    // the next stage without a page reload.
    queryClient.invalidateQueries({
      queryKey: queryKeys.documents.awaitingApproval,
    });
    // A settled request marks its own "waiting for your decision" notices
    // read on the server; without this the bell kept counting them until its
    // next five-minute poll or a reload.
    this.notifications(queryClient);
  },

  /** Invalidate module list caches. */
  modules(queryClient: QueryClient) {
    queryClient.invalidateQueries({ queryKey: queryKeys.modules.my });
    // Entering or leaving focus mode changes the enabled set as well, so the
    // focus state refreshes beside the module list instead of outliving it.
    queryClient.invalidateQueries({ queryKey: queryKeys.modules.focus });
    // Caches DERIVED from the set, read by screens that are not a module's
    // own: the storage-type picker a location edit offers reads types an
    // enabled module contributed, and switching that module off left them on
    // screen for the whole staleTime — the toggle answered 200 and nothing
    // else moved. A cache that grows its contents from who is enabled belongs
    // here beside the list itself.
    queryClient.invalidateQueries({ queryKey: queryKeys.storages.types });
  },

  /** Invalidate recipe tag caches. */
  recipeTags(queryClient: QueryClient) {
    queryClient.invalidateQueries({ queryKey: queryKeys.recipes.tags });
  },

  /** Invalidate API key caches. */
  apiKeys(queryClient: QueryClient) {
    queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys.all });
  },

  /** Invalidate maker caches (BoM + production orders + breakdown). */
  maker(queryClient: QueryClient, orderId?: string) {
    queryClient.invalidateQueries({ queryKey: queryKeys.maker.all });
    this.stockMoves(queryClient);
    if (orderId) {
      queryClient.invalidateQueries({
        queryKey: queryKeys.maker.productionDetail(orderId),
      });
    }
  },
};
