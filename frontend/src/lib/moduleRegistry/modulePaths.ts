/**
 * Every module's static paths, read without importing the module.
 *
 * The registry only ever holds the modules an organization has switched on —
 * `registerModules` imports exactly those — so `NotFoundPage` asking the
 * registry which module owns a path could never name a module that is off,
 * and its "module not enabled" screen was unreachable by construction. The
 * answer has to exist before any chunk is loaded, which is what this table
 * is: paths only, no components, no API layer, nothing a signed-out reader
 * or a switched-off module should pull in.
 *
 * A module's settings sections (`/settings/<path>`) are paths it owns too.
 *
 * Kept honest by `modulePaths.test.ts`, which registers every module and
 * compares — adding or moving a route without touching this table fails
 * there, and a module that owns no path is deliberately absent (the same
 * comparison reads its absence as "no paths").
 */
export interface ModulePaths {
  basePath: string | null;
  paths: readonly string[];
}

export const MODULE_PATHS: Readonly<Record<string, ModulePaths>> = {
  approvals: {
    basePath: "/approvals",
    paths: [
      "/approvals",
      "/approvals/workflows",
      "/settings/modules/approvals",
    ],
  },
  warehouse: {
    basePath: "/warehouse",
    paths: [
      "/warehouse",
      "/warehouse/all",
      "/warehouse/todo",
      "/warehouse/board",
      "/warehouse/approvals",
      "/warehouse/history",
      "/warehouse/register",
      "/warehouse/scan",
      "/warehouse/receive",
      "/warehouse/issue",
      "/warehouse/move",
      "/warehouse/templates",
      "/warehouse/putaway-rules",
      "/warehouse/location-settings",
      "/warehouse/occupancy",
      "/warehouse/settings",
      "/warehouse/profile",
      "/warehouse/periods",
      "/warehouse/documents/:id",
    ],
  },
  equipment: {
    basePath: "/equipment",
    paths: [
      "/equipment",
      "/equipment/add",
      "/equipment/assets",
      "/equipment/my",
      "/equipment/categories",
      "/equipment/templates",
      "/equipment/locations",
      "/equipment/campaigns",
      "/equipment/campaigns/:id",
      "/equipment/settings",
      "/equipment/:id",
      "/equipment/:id/edit",
    ],
  },
  example_widgets: { basePath: "/widgets", paths: ["/widgets"] },
  inventory: {
    basePath: "/inventory",
    paths: [
      "/inventory",
      "/inventory/items",
      "/inventory/items/archived",
      "/inventory/items/add",
      "/inventory/items/:id",
      "/inventory/stock",
      "/inventory/lots",
      "/inventory/stock/as-of",
      "/inventory/lots/:id",
      "/inventory/moves",
      "/inventory/labels",
      "/inventory/categories",
      "/inventory/scan",
    ],
  },
  launcher: { basePath: null, paths: ["/"] },
  maker: {
    basePath: "/maker",
    paths: [
      "/maker",
      "/maker/recipes/:recipeId",
      "/maker/production",
      "/maker/production/:orderId",
      "/maker/settings",
      "/maker/bom",
    ],
  },
  partners: { basePath: "/partners", paths: ["/partners"] },
  // Modules whose only screen is a settings section: the section's address
  // is the path they own, so a switched-off module answers there with "this
  // module is off" and the way to the store, not with a plain 404.
  api_keys: { basePath: null, paths: ["/settings/api-keys"] },
  webhooks: { basePath: null, paths: ["/settings/webhooks"] },
  stats: {
    basePath: null,
    paths: [
      "/inventory/stats",
      "/inventory/stats/analytics",
      "/inventory/stats/reconciliation",
      "/settings/modules/stats",
    ],
  },
  // Rendered in the inventory shell (`ModuleRoute.shell`), owned here.
  stock_takes: {
    basePath: "/stock-takes",
    paths: [
      "/inventory/stock-takes",
      "/inventory/stock-takes/count",
      "/inventory/stock-takes/:id/counting",
      "/inventory/stock-takes/:id/report",
    ],
  },
  printing: { basePath: null, paths: ["/labels/scan/:code"] },
  purchase_orders: {
    basePath: "/purchase-orders",
    paths: [
      "/purchase-orders",
      "/purchase-orders/templates",
      "/purchase-orders/settings",
      "/purchase-orders/pricelist",
      "/purchase-orders/reorder-rules",
      "/purchase-orders/:id",
      "/purchase-orders/:id/linked-receipts",
    ],
  },
  recipes: {
    basePath: "/recipes",
    paths: [
      "/recipes",
      "/recipes/settings",
      "/recipes/ingredient-data",
      "/recipes/unlinked-ingredients",
      "/recipes/:id",
      "/recipes/meal-planner",
      "/recipes/meal-planner/:id",
    ],
  },
  shopping_lists: {
    basePath: "/shopping-lists",
    paths: ["/shopping-lists", "/shopping-lists/:id"],
  },
  // Rendered in the inventory shell (`ModuleRoute.shell`), owned here.
  spaces: {
    basePath: null,
    paths: [
      "/inventory/locations",
      "/inventory/locations/zone/:zoneId",
      "/inventory/locations/archived",
      "/inventory/locations/:id",
    ],
  },
};
