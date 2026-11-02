/**
 * Contract smoke test: verifies that key API routes expected by the frontend
 * exist in the backend OpenAPI schema.
 *
 * Routes come from `src/types/api-routes.ts` (auto-generated via `npm run generate:api-types`).
 * If this test fails after adding a new route, run `npm run generate:api-types` to refresh.
 */
import { describe, expect, it } from "vitest";

import { API_ROUTES } from "@/types/api-routes";

/**
 * Routes that the frontend expects to exist in the BE OpenAPI spec.
 * Add new routes here as the frontend grows.
 */
const REQUIRED_ROUTES = [
  // Auth
  "/api/v1/auth/login",
  "/api/v1/auth/refresh",

  // Items
  "/api/v1/items",
  "/api/v1/items/{item_id}",
  "/api/v1/items/{item_id}/consume",

  // Categories
  "/api/v1/categories",

  // Storage locations
  "/api/v1/locations",
  "/api/v1/locations/tree",

  // Documents
  "/api/v1/warehouse/documents",
  "/api/v1/warehouse/corrections",
  "/api/v1/warehouse/documents/lookup/{number}",

  // Stats
  "/api/v1/stats/overview",
  "/api/v1/stats/expense-forecast",

  // Recipes
  "/api/v1/recipes",

  // Shopping lists
  "/api/v1/shopping-lists",

  // Webhooks
  "/api/v1/webhooks/endpoints",
  "/api/v1/webhooks/endpoints/{webhook_id}/deliveries",

  // Partners
  "/api/v1/partners",

  // Approvals
  "/api/v1/approvals/workflows",
  "/api/v1/approvals/requests",

  // Modules
  "/api/v1/modules/my",
  "/api/v1/modules/toggle",

  // Product templates
  "/api/v1/items/product-templates/{template_id}",

  // Labels
  "/api/v1/labels/pool",

  // Organization
  "/api/v1/organizations",
] as const;

const routeSet = new Set<string>(API_ROUTES as readonly string[]);

describe("OpenAPI route existence smoke test", () => {
  it("routes manifest is populated", () => {
    expect(API_ROUTES.length).toBeGreaterThan(50);
  });

  it.each(REQUIRED_ROUTES)("route exists: %s", (route) => {
    expect(routeSet.has(route)).toBe(true);
  });
});
