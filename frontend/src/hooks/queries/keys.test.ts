import { describe, expect, it } from "vitest";

import { queryKeys } from "./keys";

describe("queryKeys factory", () => {
  describe("items", () => {
    it("all is the items root key", () => {
      expect(queryKeys.items.all).toEqual(["items"]);
    });
    it("history is a stable array", () => {
      expect(queryKeys.items.history).toEqual(["items", "history"]);
    });
    it("archived is a stable array", () => {
      expect(queryKeys.items.archived).toEqual(["items", "archived"]);
    });
    it("detail builds a per-id key under the namespace root", () => {
      // Under the ["items"] root on purpose: the prefix invalidations every
      // stock writer clears must reach an open item card.
      expect(queryKeys.items.detail("abc")).toEqual(["items", "detail", "abc"]);
    });
    it("search builds a per-query key", () => {
      expect(queryKeys.items.search("milk")).toEqual(["items-search", "milk"]);
    });
    it("itemHistory builds a per-item history key", () => {
      expect(queryKeys.items.itemHistory("xyz")).toEqual([
        "items",
        "xyz",
        "history",
      ]);
    });
    it("storageItems builds a per-storage key", () => {
      expect(queryKeys.items.storageItems("s1")).toEqual([
        "storage-items",
        "s1",
      ]);
    });
    it("attachments builds a per-item key", () => {
      expect(queryKeys.items.attachments("i1")).toEqual(["attachments", "i1"]);
    });
  });

  describe("storages", () => {
    it("all/tree/zones/types are stable arrays", () => {
      expect(queryKeys.storages.all).toEqual(["storages"]);
      expect(queryKeys.storages.tree).toEqual(["storages-tree"]);
      expect(queryKeys.storages.types).toEqual(["storage-types"]);
    });
    it("detail/items/breadcrumb take an id", () => {
      expect(queryKeys.storages.detail("s")).toEqual([
        "storages",
        "detail",
        "s",
      ]);
      expect(queryKeys.storages.items("s")).toEqual(["storage-items", "s"]);
      expect(queryKeys.storages.breadcrumb("s")).toEqual([
        "storage-breadcrumb",
        "s",
      ]);
    });
  });

  describe("categories", () => {
    it("all is a stable array", () => {
      expect(queryKeys.categories.all).toEqual(["categories"]);
    });
  });

  describe("stats", () => {
    it("all stat sub-keys are stable arrays", () => {
      expect(queryKeys.stats.overview).toEqual(["stats", "overview"]);
      expect(queryKeys.stats.byStorage).toEqual(["stats", "by-storage"]);
      expect(queryKeys.stats.byCategory).toEqual(["stats", "by-category"]);
      expect(queryKeys.stats.expiryForecast).toEqual([
        "stats",
        "expiry-forecast",
      ]);
      expect(queryKeys.stats.costAnalysis("month")).toEqual([
        "stats",
        "cost-analysis",
        "month",
      ]);
      // Different periods are different cache entries.
      expect(queryKeys.stats.costAnalysis("week")).not.toEqual(
        queryKeys.stats.costAnalysis("month"),
      );
      expect(queryKeys.stats.rotationAnalysis).toEqual([
        "stats",
        "rotation-analysis",
      ]);
      expect(queryKeys.stats.smartAlerts).toEqual(["stats", "smart-alerts"]);
      expect(queryKeys.stats.expenseForecast("month")).toEqual([
        "stats",
        "expense-forecast",
        "month",
      ]);
      expect(queryKeys.stats.purchasePatterns).toEqual([
        "stats",
        "purchase-patterns",
      ]);
      expect(queryKeys.stats.launcherBadge).toEqual([
        "stats",
        "overview",
        "launcher-badge",
      ]);
      // Under `overview`, so the writes that invalidate it refresh the rows.
      expect(queryKeys.stats.lowStock).toEqual([
        "stats",
        "overview",
        "low-stock",
      ]);
    });
  });

  describe("labels", () => {
    it("all is stable", () => {
      expect(queryKeys.labels.all).toEqual(["labels"]);
    });
  });

  describe("webhooks", () => {
    it("all/events are stable; deliveries takes id+cursor", () => {
      expect(queryKeys.webhooks.all).toEqual(["webhooks"]);
      expect(queryKeys.webhooks.events).toEqual(["webhook-events"]);
      expect(queryKeys.webhooks.deliveries("w", "cur")).toEqual([
        "webhook-deliveries",
        "w",
        "cur",
      ]);
    });
  });

  describe("organization", () => {
    it("detail and members are stable arrays", () => {
      expect(queryKeys.organization.detail).toEqual(["organization"]);
      expect(queryKeys.organization.members).toEqual(["organization-members"]);
    });
  });

  describe("admin", () => {
    it("all admin sub-keys are stable arrays or take id/params", () => {
      expect(queryKeys.admin.registrationRequests).toEqual([
        "registration-requests",
      ]);
      expect(queryKeys.admin.organizations).toEqual(["cloud-admin-orgs"]);
      expect(queryKeys.admin.stats).toEqual(["cloud-admin-stats"]);
      expect(queryKeys.admin.allModules).toEqual(["cloud-admin-all-modules"]);
      expect(queryKeys.admin.aiUsage(7)).toEqual(["cloud-ai-usage", 7]);
      expect(queryKeys.admin.orgAiStats("o")).toEqual(["org-ai-stats", "o"]);
      expect(queryKeys.admin.systemSettings).toEqual(["cloud-system-settings"]);
      expect(queryKeys.admin.cloudOrganizations).toEqual([
        "cloud-organizations",
      ]);
      expect(queryKeys.admin.initStatus).toEqual(["init-status"]);
      expect(queryKeys.admin.appVersion).toEqual(["app-version"]);
    });
  });

  describe("notifications", () => {
    it("all is stable", () => {
      expect(queryKeys.notifications.all).toEqual(["notifications"]);
    });
  });

  describe("shoppingLists", () => {
    it("all/active are stable; detail and suggestions take id", () => {
      expect(queryKeys.shoppingLists.all).toEqual(["shopping-lists"]);
      expect(queryKeys.shoppingLists.active).toEqual(["active-shopping-list"]);
      expect(queryKeys.shoppingLists.detail("l")).toEqual([
        "shopping-lists",
        "detail",
        "l",
      ]);
      expect(queryKeys.shoppingLists.suggestions("l")).toEqual([
        "shopping-suggestions",
        "l",
      ]);
    });
  });

  describe("recipes", () => {
    it("all/available vary with params; detail/availability/nutrition/history/cost take id+args", () => {
      expect(queryKeys.recipes.all()).toEqual(["recipes"]);
      expect(queryKeys.recipes.all({ q: "a" })).toEqual([
        "recipes",
        { q: "a" },
      ]);
      expect(queryKeys.recipes.available()).toEqual(["recipes", "available"]);
      expect(queryKeys.recipes.available({ q: "a" })).toEqual([
        "recipes",
        "available",
        { q: "a" },
      ]);
      expect(queryKeys.recipes.detail("r")).toEqual(["recipes", "detail", "r"]);
      expect(queryKeys.recipes.availability("r", 4)).toEqual([
        "recipes",
        "detail",
        "r",
        "availability",
        4,
      ]);
      // The prefix a stock write invalidates has to reach the parameterised
      // key, whatever servings an open card asked for.
      expect(
        queryKeys.recipes
          .availability("r", 4)
          .slice(0, queryKeys.recipes.availabilityAll("r").length),
      ).toEqual(queryKeys.recipes.availabilityAll("r"));
      expect(queryKeys.recipes.nutrition("r", 4)).toEqual([
        "recipes",
        "detail",
        "r",
        "nutrition",
        4,
      ]);
      expect(queryKeys.recipes.history("r")).toEqual([
        "recipes",
        "detail",
        "r",
        "history",
      ]);
      expect(queryKeys.recipes.cost("r", 2)).toEqual([
        "recipes",
        "detail",
        "r",
        "cost",
        2,
      ]);
      expect(queryKeys.recipes.tags).toEqual(["recipe-tags"]);
    });
  });

  describe("mealPlans", () => {
    it("all varies with params; detail/suggestions/exclusions have expected shape", () => {
      expect(queryKeys.mealPlans.all()).toEqual(["meal-plans"]);
      expect(queryKeys.mealPlans.all({})).toEqual(["meal-plans", {}]);
      expect(queryKeys.mealPlans.detail("m")).toEqual([
        "meal-plans",
        "detail",
        "m",
      ]);
      expect(queryKeys.mealPlans.suggestions({})).toEqual([
        "meal-plan-suggestions",
        {},
      ]);
      expect(queryKeys.mealPlans.exclusions).toEqual(["shopping-exclusions"]);
    });
  });

  describe("stockTakes", () => {
    it("all is the namespace root; list takes status; detail takes id; launcherActions is stable", () => {
      expect(queryKeys.stockTakes.all).toEqual(["stock-takes"]);
      expect(queryKeys.stockTakes.list()).toEqual(["stock-takes", ""]);
      expect(queryKeys.stockTakes.list("in_progress")).toEqual([
        "stock-takes",
        "in_progress",
      ]);
      expect(queryKeys.stockTakes.detail("s")).toEqual([
        "stock-takes",
        "detail",
        "s",
      ]);
      expect(queryKeys.stockTakes.report("s")).toEqual([
        "stock-takes",
        "detail",
        "s",
        "report",
      ]);
      expect(queryKeys.stockTakes.launcherActions).toEqual([
        "stock-takes",
        "in_progress",
        "launcher-actions",
      ]);
    });
  });

  describe("modules", () => {
    it("my/available are stable arrays", () => {
      expect(queryKeys.modules.my).toEqual(["my-modules"]);
      expect(queryKeys.modules.available).toEqual(["modules", "available"]);
    });
  });

  describe("uoms", () => {
    it("all and categories are stable arrays", () => {
      expect(queryKeys.uoms.all).toEqual(["uoms"]);
      expect(queryKeys.uoms.categories).toEqual(["uoms", "categories"]);
    });
  });

  describe("announcements", () => {
    it("active is stable", () => {
      expect(queryKeys.announcements.active).toEqual([
        "announcements",
        "active",
      ]);
    });
  });

  describe("documents", () => {
    it("all/corrections/profile/presets/periods stable; detail/approval/register take args", () => {
      expect(queryKeys.documents.all).toEqual(["documents"]);
      expect(queryKeys.documents.detail("d")).toEqual(["documents", "d"]);
      expect(queryKeys.documents.corrections("d")).toEqual([
        "documents",
        "d",
        "corrections",
      ]);
      expect(queryKeys.documents.profile).toEqual(["document-profile"]);
      expect(queryKeys.documents.presets).toEqual([
        "document-profile",
        "presets",
      ]);
      expect(queryKeys.documents.periods).toEqual(["inventory-periods"]);
      expect(queryKeys.documents.register({})).toEqual([
        "documents-register",
        {},
      ]);
    });
  });

  describe("partners", () => {
    it("all is stable; detail/employees take id/search", () => {
      expect(queryKeys.partners.all).toEqual(["partners"]);
      expect(queryKeys.partners.detail("p")).toEqual(["partners", "p"]);
      expect(queryKeys.partners.employees("foo")).toEqual([
        "partners",
        "employees",
        "foo",
      ]);
    });
  });

  describe("equipment", () => {
    it("top-level keys are stable; sub-objects have expected shape", () => {
      expect(queryKeys.equipment.all).toEqual(["equipment"]);
      expect(queryKeys.equipment.dashboard).toEqual(["equipment", "dashboard"]);
      expect(queryKeys.equipment.assets.all).toEqual(["equipment", "assets"]);
      expect(queryKeys.equipment.assets.list({})).toEqual([
        "equipment",
        "assets",
        "list",
        {},
      ]);
      expect(queryKeys.equipment.assets.detail("a")).toEqual([
        "equipment",
        "assets",
        "detail",
        "a",
      ]);
      expect(queryKeys.equipment.assignments.active).toEqual([
        "equipment",
        "assignments",
        "active",
      ]);
      expect(queryKeys.equipment.assignments.itemHistory("i")).toEqual([
        "equipment",
        "assignments",
        "item",
        "i",
      ]);
      expect(queryKeys.equipment.warrantyAlerts()).toEqual([
        "equipment",
        "warranty-alerts",
        30,
      ]);
      expect(queryKeys.equipment.warrantyAlerts(60)).toEqual([
        "equipment",
        "warranty-alerts",
        60,
      ]);
      expect(queryKeys.equipment.warrantyBadge).toEqual([
        "equipment",
        "warranty-alerts",
        30,
        "launcher-badge",
      ]);
      expect(queryKeys.equipment.maintenance.all).toEqual([
        "equipment",
        "maintenance",
      ]);
      expect(queryKeys.equipment.maintenance.itemLogs("i")).toEqual([
        "equipment",
        "maintenance",
        "item",
        "i",
      ]);
      expect(queryKeys.equipment.templates).toEqual(["equipment", "templates"]);
      expect(queryKeys.equipment.placeholders).toEqual([
        "equipment",
        "placeholders",
      ]);
      expect(queryKeys.equipment.models).toEqual(["equipment", "models"]);
      expect(queryKeys.equipment.campaigns.list).toEqual([
        "equipment",
        "campaigns",
      ]);
      expect(queryKeys.equipment.campaigns.detail("c")).toEqual([
        "equipment",
        "campaigns",
        "c",
      ]);
      expect(queryKeys.equipment.valuation.fleet).toEqual([
        "equipment",
        "valuation",
        "fleet",
      ]);
      expect(queryKeys.equipment.valuation.asset("a")).toEqual([
        "equipment",
        "valuation",
        "asset",
        "a",
      ]);
    });
  });

  describe("purchaseOrders", () => {
    it("all is stable; list/detail/linkedReceipts take id args", () => {
      expect(queryKeys.purchaseOrders.all).toEqual(["purchase-orders"]);
      expect(queryKeys.purchaseOrders.list({ limit: 10, offset: 0 })).toEqual([
        "purchase-orders",
        { limit: 10, offset: 0 },
      ]);
      expect(queryKeys.purchaseOrders.detail("p")).toEqual([
        "purchase-orders",
        "p",
      ]);
      expect(queryKeys.purchaseOrders.linkedReceipts("p")).toEqual([
        "purchase-orders",
        "p",
        "linked-receipts",
      ]);
    });
  });

  describe("apiKeys", () => {
    it("all is stable", () => {
      expect(queryKeys.apiKeys.all).toEqual(["api-keys"]);
    });
  });

  describe("printing", () => {
    it("labelScan takes a code", () => {
      expect(queryKeys.printing.labelScan("abc")).toEqual([
        "label-scan",
        "abc",
      ]);
    });
  });

  describe("onboarding", () => {
    it("profiles is stable", () => {
      expect(queryKeys.onboarding.profiles).toEqual(["onboarding", "profiles"]);
    });
  });

  describe("templates", () => {
    it("list/placeholders take a module name", () => {
      expect(queryKeys.templates.list("recipes")).toEqual([
        "templates",
        "recipes",
      ]);
      expect(queryKeys.templates.placeholders("recipes")).toEqual([
        "templates",
        "recipes",
        "placeholders",
      ]);
    });
  });

  describe("users", () => {
    it("orgMembers is stable", () => {
      expect(queryKeys.users.orgMembers).toEqual(["users", "org-members"]);
    });
  });

  describe("commandPalette", () => {
    it("search takes query and enabled modules", () => {
      expect(queryKeys.commandPalette.search("foo", ["m1"])).toEqual([
        "command-palette-search",
        "foo",
        ["m1"],
      ]);
    });
  });

  describe("settings", () => {
    it("detail is stable", () => {
      expect(queryKeys.settings.detail).toEqual(["settings"]);
    });
  });

  describe("aiConnections", () => {
    it("all/purposes/bindings are stable", () => {
      expect(queryKeys.aiConnections.all).toEqual(["ai-connections"]);
      expect(queryKeys.aiConnections.purposes).toEqual([
        "ai-connections",
        "purposes",
      ]);
      expect(queryKeys.aiConnections.bindings).toEqual([
        "ai-connections",
        "bindings",
      ]);
    });
  });

  describe("keys that sit under a family root", () => {
    it("stock lots list keys carry the filters, so two filters never share a cache entry", () => {
      const open = queryKeys.stockLots.list({ status: "available" });
      const held = queryKeys.stockLots.list({ status: "quarantine" });
      expect(open).toEqual(["stock-lots", "list", { status: "available" }]);
      expect(open).not.toEqual(held);
      // A stock write invalidates the family prefix; both must sit under it.
      expect(open.slice(0, 1)).toEqual(queryKeys.stockLots.all);
      expect(held.slice(0, 1)).toEqual(queryKeys.stockLots.all);
    });

    it("document keys that name a rule, a register page or a destination differ per input", () => {
      expect(queryKeys.documents.replenishmentProposal("r1")).toEqual([
        "documents",
        "replenishment-proposal",
        "r1",
      ]);
      expect(queryKeys.documents.replenishmentProposal("r1")).not.toEqual(
        queryKeys.documents.replenishmentProposal("r2"),
      );
      expect(queryKeys.documents.registerRows({ page: 1 })).toEqual([
        "documents-register-rows",
        { page: 1 },
      ]);
      expect(queryKeys.documents.registerRows({ page: 1 })).not.toEqual(
        queryKeys.documents.registerRows({ page: 2 }),
      );
    });

    it("putaway preview is keyed by destination and by the unsaved lines, so a changed sheet is asked again", () => {
      const lines = [{ product: "p", qty: 1 }];
      expect(queryKeys.documents.putawayPreview("loc-1", lines)).toEqual([
        "documents",
        "putaway-preview",
        "loc-1",
        lines,
      ]);
      expect(queryKeys.documents.putawayPreview("loc-1", lines)).not.toEqual(
        queryKeys.documents.putawayPreview("loc-2", lines),
      );
      expect(queryKeys.documents.putawayPreview(null, lines)).not.toEqual(
        queryKeys.documents.putawayPreview("loc-1", lines),
      );
      expect(queryKeys.documents.putawayPreview("loc-1", [])).not.toEqual(
        queryKeys.documents.putawayPreview("loc-1", lines),
      );
    });

    it("campaign scope previews are keyed by both the scope type and the filter", () => {
      const key = queryKeys.equipment.campaigns.scopePreview("category", "f1");
      expect(key).toEqual([
        "equipment",
        "campaigns",
        "scope-preview",
        "category",
        "f1",
      ]);
      expect(key).not.toEqual(
        queryKeys.equipment.campaigns.scopePreview("category", "f2"),
      );
      expect(key).not.toEqual(
        queryKeys.equipment.campaigns.scopePreview("location", "f1"),
      );
      expect(key.slice(0, 2)).toEqual(queryKeys.equipment.campaigns.list);
    });
  });

  describe("maker keys", () => {
    const root = queryKeys.maker.all;

    it("every bill-of-materials key starts at the maker root and differs per template", () => {
      expect(queryKeys.maker.bom("t1")).toEqual(["maker", "bom", "t1"]);
      expect(queryKeys.maker.bomTree("t1")).toEqual([
        "maker",
        "bom",
        "tree",
        "t1",
      ]);
      expect(queryKeys.maker.bomSummary("t1")).toEqual([
        "maker",
        "bom",
        "summary",
        "t1",
      ]);
      expect(queryKeys.maker.bomTemplateIds()).toEqual([
        "maker",
        "bom",
        "template-ids",
      ]);
      for (const key of [
        queryKeys.maker.bom("t1"),
        queryKeys.maker.bomTree("t1"),
        queryKeys.maker.bomSummary("t1"),
        queryKeys.maker.bomTemplateIds(),
      ]) {
        expect(key.slice(0, 1)).toEqual(root);
      }
      expect(queryKeys.maker.bom("t1")).not.toEqual(queryKeys.maker.bom("t2"));
      expect(queryKeys.maker.bomTree("t1")).not.toEqual(
        queryKeys.maker.bomTree("t2"),
      );
      expect(queryKeys.maker.bomSummary("t1")).not.toEqual(
        queryKeys.maker.bomSummary("t2"),
      );
    });

    it("the batch summary key ignores the order of the ids and leaves the caller's list alone", () => {
      const ids = ["b", "c", "a"];
      const key = queryKeys.maker.bomSummaryBatch(ids);
      expect(key).toEqual([
        "maker",
        "bom",
        "summary",
        "batch",
        ["a", "b", "c"],
      ]);
      // Sorting in place would reorder the array the screen renders from.
      expect(ids).toEqual(["b", "c", "a"]);
      expect(queryKeys.maker.bomSummaryBatch(["c", "a", "b"])).toEqual(key);
      expect(queryKeys.maker.bomSummaryBatch(["a", "b"])).not.toEqual(key);
    });

    it("cost estimates fall back to the default recipe and a quantity of one, and differ once either is named", () => {
      expect(queryKeys.maker.bomCostEstimate("t1")).toEqual([
        "maker",
        "bom",
        "cost-estimate",
        "t1",
        "default",
        "1",
      ]);
      expect(queryKeys.maker.bomCostEstimate("t1", "r1", "5")).toEqual([
        "maker",
        "bom",
        "cost-estimate",
        "t1",
        "r1",
        "5",
      ]);
    });

    it("the production list is the bare prefix without params and a narrower key with them", () => {
      expect(queryKeys.maker.productionList()).toEqual(["maker", "production"]);
      const filtered = queryKeys.maker.productionList({ status: "done" });
      expect(filtered).toEqual(["maker", "production", { status: "done" }]);
      expect(filtered.slice(0, 2)).toEqual(queryKeys.maker.productionList());
    });

    it("production order keys stay under the production prefix and differ per order", () => {
      expect(queryKeys.maker.productionDetail("o1")).toEqual([
        "maker",
        "production",
        "o1",
      ]);
      expect(queryKeys.maker.productionStockMoves("o1")).toEqual([
        "maker",
        "production",
        "o1",
        "stock-moves",
      ]);
      expect(queryKeys.maker.productionStockMoves()).toEqual([
        "maker",
        "production",
        "",
        "stock-moves",
      ]);
      expect(queryKeys.maker.productionDetail("o1")).not.toEqual(
        queryKeys.maker.productionDetail("o2"),
      );
      expect(queryKeys.maker.productionStockMoves("o1")).not.toEqual(
        queryKeys.maker.productionStockMoves("o2"),
      );
    });

    it("the monthly result is keyed by the number of months, so a longer window is fetched afresh", () => {
      expect(queryKeys.maker.monthlyResult(6)).toEqual([
        "maker",
        "production",
        "monthly-result",
        6,
      ]);
      expect(queryKeys.maker.monthlyResult(6)).not.toEqual(
        queryKeys.maker.monthlyResult(12),
      );
    });

    it("a breakdown is keyed by template, quantity and recipe, with no recipe written as null", () => {
      expect(queryKeys.maker.breakdown("t1", "2")).toEqual([
        "maker",
        "breakdown",
        "t1",
        "2",
        null,
      ]);
      expect(queryKeys.maker.breakdown("t1", "2", null)).toEqual(
        queryKeys.maker.breakdown("t1", "2"),
      );
      expect(queryKeys.maker.breakdown("t1", "2", "r1")).toEqual([
        "maker",
        "breakdown",
        "t1",
        "2",
        "r1",
      ]);
      expect(queryKeys.maker.breakdown("t1", "3")).not.toEqual(
        queryKeys.maker.breakdown("t1", "2"),
      );
    });

    it("recipe availability is keyed by recipe, batch count and location", () => {
      const key = queryKeys.maker.recipeAvailability("r1", "2", "loc");
      expect(key).toEqual([
        "maker",
        "recipes",
        "availability",
        "r1",
        "2",
        "loc",
      ]);
      expect(key.slice(0, 2)).toEqual(queryKeys.maker.recipesAll);
      expect(key).not.toEqual(
        queryKeys.maker.recipeAvailability("r1", "3", "loc"),
      );
      expect(key).not.toEqual(
        queryKeys.maker.recipeAvailability("r1", "2", undefined),
      );
    });
  });

  describe("idempotency", () => {
    it("id-based builders return equal tuples for equal input", () => {
      expect(queryKeys.storages.detail("x")).toEqual(
        queryKeys.storages.detail("x"),
      );
    });
    it("id-based builders return different tuples for different input", () => {
      expect(queryKeys.items.detail("y")).not.toBe(queryKeys.items.detail("z"));
    });
  });
});
