import { describe, it, expect, vi, type Mock } from "vitest";
import { QueryClient, QueryObserver } from "@tanstack/react-query";
import { invalidation } from "./invalidation";
import { queryKeys } from "@/hooks/queries/keys";

const makeClient = () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  vi.spyOn(client, "invalidateQueries");
  return client;
};

describe("invalidation helpers", () => {
  describe("items()", () => {
    it("invalidates items and stats caches", () => {
      const qc = makeClient();
      invalidation.items(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.items.all);
      expect(keys).toContainEqual(queryKeys.stats.overview);
    });

    it("marks the short-product rows stale, whichever module setting they were fetched under", () => {
      const qc = new QueryClient();
      for (const hidden of [true, false]) {
        qc.setQueryData([...queryKeys.stats.lowStock, hidden], []);
        qc.setQueryData([...queryKeys.stats.launcherBadge, hidden], {});
      }
      invalidation.items(qc);
      for (const hidden of [true, false]) {
        expect(
          qc.getQueryState([...queryKeys.stats.lowStock, hidden])
            ?.isInvalidated,
        ).toBe(true);
        expect(
          qc.getQueryState([...queryKeys.stats.launcherBadge, hidden])
            ?.isInvalidated,
        ).toBe(true);
      }
    });

    it("also invalidates storage-items when storageId provided", () => {
      const qc = makeClient();
      invalidation.items(qc, "s-1");
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.items.storageItems("s-1"));
    });
  });

  describe("storages()", () => {
    it("invalidates storages, storages-tree, items, stats", () => {
      const qc = makeClient();
      invalidation.storages(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.storages.all);
      expect(keys).toContainEqual(queryKeys.storages.tree);
      expect(keys).toContainEqual(queryKeys.items.all);
      expect(keys).toContainEqual(queryKeys.stats.overview);
    });

    it("also invalidates individual storage when storageId provided", () => {
      const qc = makeClient();
      invalidation.storages(qc, "s-2");
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.storages.detail("s-2"));
      expect(keys).toContainEqual(queryKeys.items.storageItems("s-2"));
    });
  });

  describe("storageDeleted()", () => {
    it("refreshes the location lists but never asks again for the deleted one", () => {
      const qc = new QueryClient();
      const gone = "s-gone";
      const asksForGone = [
        queryKeys.storages.detail(gone),
        [...queryKeys.storages.all, "breadcrumb", gone],
        [...queryKeys.storages.tree, "children", gone],
      ];
      const lists = [
        [...queryKeys.storages.all, "page", { limit: 50 }],
        [...queryKeys.storages.tree, "children", "s-parent"],
        queryKeys.items.all,
        queryKeys.stats.overview,
      ];
      for (const key of [...asksForGone, ...lists]) qc.setQueryData(key, {});

      invalidation.storageDeleted(qc, gone);

      for (const key of asksForGone) {
        expect(qc.getQueryState(key)?.isInvalidated).toBe(false);
      }
      for (const key of lists) {
        expect(qc.getQueryState(key)?.isInvalidated).toBe(true);
      }
    });
  });

  describe("stats()", () => {
    it("invalidates stats caches", () => {
      const qc = makeClient();
      invalidation.stats(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.stats.overview);
    });
  });

  describe("shoppingLists()", () => {
    it("invalidates shopping list caches", () => {
      const qc = makeClient();
      invalidation.shoppingLists(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.shoppingLists.all);
      expect(keys).toContainEqual(queryKeys.shoppingLists.active);
    });
  });

  describe("recipes()", () => {
    it("invalidates recipes cache", () => {
      const qc = makeClient();
      invalidation.recipes(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.recipes.all());
    });

    it("also invalidates individual recipe when recipeId provided", () => {
      const qc = makeClient();
      invalidation.recipes(qc, "r-1");
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.recipes.detail("r-1"));
    });

    it("invalidates the recipe-tags key too", () => {
      const qc = makeClient();
      invalidation.recipes(qc, "r-1");
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      // New tags (e.g. from a freshly created recipe) must appear in the
      // filter bar without a page reload — the tags key lives outside the
      // ["recipes"] prefix, so every recipe mutation used to skip it.
      expect(keys).toContainEqual(queryKeys.recipes.tags);
    });
  });

  describe("organization()", () => {
    it("invalidates organization and members caches", () => {
      const qc = makeClient();
      invalidation.organization(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.organization.detail);
      expect(keys).toContainEqual(queryKeys.organization.members);
    });

    it("invalidates what the country supplies, so Warehouse settings read the new one without a reload", () => {
      const qc = makeClient();
      invalidation.organization(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.documents.taxRatesCountry);
    });
  });

  describe("notifications()", () => {
    it("invalidates notifications cache", () => {
      const qc = makeClient();
      invalidation.notifications(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.notifications.all);
    });
  });

  describe("admin()", () => {
    it("invalidates the admin family, so a changed user list is fetched again", () => {
      const qc = makeClient();
      invalidation.admin(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toEqual([queryKeys.admin.all]);
    });
  });

  describe("storageTypes()", () => {
    it("invalidates only the storage types, so a new type shows in the pickers without reloading every location", () => {
      const qc = makeClient();
      invalidation.storageTypes(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toEqual([queryKeys.storages.types]);
    });
  });

  describe("equipment()", () => {
    it("invalidates equipment, dashboard, models, maintenance, campaigns, items", () => {
      const qc = makeClient();
      invalidation.equipment(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.equipment.all);
      expect(keys).toContainEqual(queryKeys.equipment.dashboard);
      expect(keys).toContainEqual(queryKeys.equipment.models);
      expect(keys).toContainEqual(queryKeys.equipment.maintenance.all);
      expect(keys).toContainEqual(queryKeys.equipment.campaigns.list);
      expect(keys).toContainEqual(queryKeys.items.all);
    });

    it("also invalidates asset detail when itemId provided", () => {
      const qc = makeClient();
      invalidation.equipment(qc, "item-1");
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.equipment.assets.detail("item-1"));
    });
  });

  describe("documents()", () => {
    it("invalidates documents cache", () => {
      const qc = makeClient();
      invalidation.documents(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.documents.all);
    });

    it("also invalidates detail when docId provided", () => {
      const qc = makeClient();
      invalidation.documents(qc, "doc-1");
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.documents.detail("doc-1"));
    });

    it("marks the order a receipt was posted against out of date", () => {
      // The order screen read its received quantities from a copy that
      // stayed fresh for five minutes after the goods were posted.
      const qc = new QueryClient();
      const orderKey = queryKeys.purchaseOrders.detail("po-1");
      qc.setQueryData(orderKey, { id: "po-1" });

      invalidation.documents(qc, "doc-1");

      expect(qc.getQueryState(orderKey)?.isInvalidated).toBe(true);
    });

    it("stops offering a supplier's order the receipt has just completed", () => {
      // The receive screen loads a supplier's open orders by list query;
      // a copy younger than the staleTime offered the order received a
      // moment ago when the reader chose Receive more.
      const qc = new QueryClient();
      const openOrdersKey = queryKeys.purchaseOrders.list({
        partner_id: "supplier-1",
        status: "CONFIRMED",
        limit: 50,
      });
      qc.setQueryData(openOrdersKey, [{ id: "po-1" }]);

      invalidation.documents(qc);

      expect(qc.getQueryState(openOrdersKey)?.isInvalidated).toBe(true);
    });
  });

  describe("stockMoves()", () => {
    it.each(["items", "documents", "stockTakes", "maker", "picking"] as const)(
      "%s refreshes recipe stock counts before the five-minute staleTime",
      async (writer) => {
        const qc = new QueryClient({
          defaultOptions: { queries: { retry: false, staleTime: 300_000 } },
        });
        const listKeys = [
          queryKeys.recipes.all(),
          queryKeys.recipes.all({ search: "soup", skip: 0, limit: 20 }),
          queryKeys.recipes.all({ is_favorite: true, skip: 20, limit: 20 }),
        ];
        const before = [
          { id: "r-1", ingredients_available: 2, ingredients_total: 2 },
        ];
        const after = [
          { id: "r-1", ingredients_available: 1, ingredients_total: 2 },
        ];
        for (const key of listKeys) qc.setQueryData(key, before);
        const nutritionKey = queryKeys.recipes.nutrition("r-1", 1);
        qc.setQueryData(nutritionKey, {});
        const queryFn = vi.fn(async () => after);
        const observer = new QueryObserver(qc, {
          queryKey: listKeys[0],
          queryFn,
          staleTime: 300_000,
        });
        const unsubscribe = observer.subscribe(() => {});
        try {
          expect(observer.getCurrentResult().isStale).toBe(false);

          invalidation[writer](qc);

          for (const key of listKeys) {
            expect(qc.getQueryState(key)?.isInvalidated).toBe(true);
          }
          expect(qc.getQueryState(nutritionKey)?.isInvalidated).toBe(false);
          await vi.waitFor(() =>
            expect(observer.getCurrentResult().data).toEqual(after),
          );
          expect(queryFn).toHaveBeenCalledTimes(1);
        } finally {
          unsubscribe();
          qc.clear();
        }
      },
    );

    it.each(["items", "documents", "stockTakes", "maker"] as const)(
      "%s marks the 'I can cook' answer and every open availability stale",
      (writer) => {
        const qc = new QueryClient({
          defaultOptions: { queries: { retry: false, staleTime: 300_000 } },
        });
        const keys = [
          queryKeys.recipes.available(),
          queryKeys.recipes.available({ limit: 20 }),
          queryKeys.recipes.availability("r-1", 2),
          queryKeys.recipes.availability("r-2", 1),
        ];
        const untouched = queryKeys.recipes.history("r-1");
        for (const key of [...keys, untouched]) qc.setQueryData(key, {});

        invalidation[writer](qc);

        for (const key of keys) {
          expect(qc.getQueryState(key)?.isInvalidated).toBe(true);
        }
        expect(qc.getQueryState(untouched)?.isInvalidated).toBe(false);
      },
    );

    it("invalidates the movement ledger", () => {
      const qc = makeClient();
      invalidation.stockMoves(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.stockMoves.all);
    });

    it("rides along with every writer of stock", () => {
      // The ledger is the answer to "what just happened?" — documents, quick
      // item ops, stock takes and production all write moves, so each of
      // their invalidations must stand it back up. A stale 30 s ledger said
      // "this document moved nothing" seconds after it moved ten units.
      for (const helper of [
        invalidation.documents,
        invalidation.items,
        invalidation.stockTakes,
        invalidation.maker,
        invalidation.picking,
      ]) {
        const qc = makeClient();
        helper.call(invalidation, qc);
        const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
          (c) => (c[0] as { queryKey: unknown }).queryKey,
        );
        expect(keys).toContainEqual(queryKeys.stockMoves.all);
      }
    });
  });

  describe("picking()", () => {
    it("invalidates items, the ledger, quants, lots and the recipe's availability", () => {
      const qc = makeClient();
      invalidation.picking(qc, "r-1");
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.items.all);
      expect(keys).toContainEqual(queryKeys.stockMoves.all);
      expect(keys).toContainEqual(queryKeys.stockQuants.all);
      expect(keys).toContainEqual(queryKeys.stockLots.all);
      expect(keys).toContainEqual(queryKeys.recipes.availabilityAll("r-1"));
      expect(keys).toContainEqual(queryKeys.recipes.available());
    });

    it("invalidates the recipe's cooking history, so a session that just finished is listed", () => {
      const qc = makeClient();
      invalidation.picking(qc, "r-1");
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.recipes.history("r-1"));
    });

    it("reaches the availability card whatever servings it asked for", () => {
      // The writer knows the recipe, not the servings the open card read —
      // without the prefix the key misses and the card keeps the old shelf.
      const qc = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      });
      qc.setQueryData(queryKeys.recipes.availability("r-1", 3), {});

      invalidation.picking(qc, "r-1");

      expect(
        qc.getQueryState(queryKeys.recipes.availability("r-1", 3))
          ?.isInvalidated,
      ).toBe(true);
    });
  });

  describe("inventoryPeriods()", () => {
    it("invalidates periods cache", () => {
      const qc = makeClient();
      invalidation.inventoryPeriods(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.documents.periods);
    });
  });

  describe("mealPlans()", () => {
    it("invalidates meal plans and exclusions", () => {
      const qc = makeClient();
      invalidation.mealPlans(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.mealPlans.all());
      expect(keys).toContainEqual(queryKeys.mealPlans.exclusions);
    });

    it("also invalidates detail when planId provided", () => {
      const qc = makeClient();
      invalidation.mealPlans(qc, "plan-1");
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.mealPlans.detail("plan-1"));
    });
  });

  describe("categories()", () => {
    it("invalidates categories", () => {
      const qc = makeClient();
      invalidation.categories(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.categories.all);
    });
  });

  describe("partners()", () => {
    it("invalidates partners cache", () => {
      const qc = makeClient();
      invalidation.partners(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.partners.all);
    });
  });

  describe("templates()", () => {
    it("invalidates templates for a module", () => {
      const qc = makeClient();
      invalidation.templates(qc, "equipment");
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.templates.list("equipment"));
    });
  });

  describe("stockTakes()", () => {
    it("invalidates stock takes cache", () => {
      const qc = makeClient();
      invalidation.stockTakes(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.stockTakes.all);
    });

    it("also invalidates detail when id provided", () => {
      const qc = makeClient();
      invalidation.stockTakes(qc, "st-1");
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.stockTakes.detail("st-1"));
    });
  });

  describe("announcements()", () => {
    it("invalidates admin and active announcements", () => {
      const qc = makeClient();
      invalidation.announcements(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(["admin", "announcements"]);
      expect(keys).toContainEqual(queryKeys.announcements.active);
    });
  });

  describe("approvals()", () => {
    it("invalidates the whole approvals namespace — workflows and requests", () => {
      const qc = makeClient();
      invalidation.approvals(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      // One root, not two keys: the shapes below are pinned literally
      // because the prefix the helper clears has to be the head of the keys
      // the module reads, or the invalidation reaches neither.
      expect(keys).toContainEqual(queryKeys.approvals.all);
      expect(queryKeys.approvals.all).toEqual(["approvals"]);
      expect(queryKeys.approvals.requests).toEqual(["approvals", "requests"]);
      expect(queryKeys.approvals.workflows).toEqual(["approvals", "workflows"]);
    });

    it("refreshes the bell, which a settled request has just emptied", () => {
      const qc = makeClient();
      invalidation.approvals(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.notifications.all);
    });
  });

  describe("modules()", () => {
    it("invalidates my modules cache", () => {
      const qc = makeClient();
      invalidation.modules(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.modules.my);
    });

    it("also invalidates the caches derived from the set", () => {
      // The storage-type picker is read by a core screen (the location edit)
      // and filled by whatever module is enabled: switching one off left its
      // types on screen for the cache's whole staleTime.
      const qc = makeClient();
      invalidation.modules(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.storages.types);
      expect(keys).toContainEqual(queryKeys.modules.focus);
    });
  });

  describe("recipeTags()", () => {
    it("invalidates recipe tags cache", () => {
      const qc = makeClient();
      invalidation.recipeTags(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.recipes.tags);
    });
  });

  describe("apiKeys()", () => {
    it("invalidates API keys cache", () => {
      const qc = makeClient();
      invalidation.apiKeys(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.apiKeys.all);
    });
  });

  describe("purchaseOrders()", () => {
    it("invalidates purchase orders cache", () => {
      const qc = makeClient();
      invalidation.purchaseOrders(qc);
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.purchaseOrders.all);
    });

    it("also invalidates detail when poId provided", () => {
      const qc = makeClient();
      invalidation.purchaseOrders(qc, "po-1");
      const keys = (qc.invalidateQueries as unknown as Mock).mock.calls.map(
        (c) => (c[0] as { queryKey: unknown }).queryKey,
      );
      expect(keys).toContainEqual(queryKeys.purchaseOrders.detail("po-1"));
    });
  });
});
