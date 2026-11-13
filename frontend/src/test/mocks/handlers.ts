import { http, HttpResponse } from "msw";
import type { components } from "@/types/api-generated";
import { onePage } from "@/test/mocks/page";

export const handlers = [
  // No country comes with a document preset unless a test says so.
  http.get("*/api/v1/onboarding/country-preset", () =>
    HttpResponse.json({ preset: null }),
  ),

  // Stock covers every dispatch unless a test says otherwise.
  http.post("/api/v1/warehouse/picking/coverage", () =>
    HttpResponse.json({ documents: [] }),
  ),

  // Auth handlers
  http.post("/api/auth/login", () => {
    return HttpResponse.json({
      access_token: "mocked_access_token",
      token_type: "bearer",
    });
  }),

  http.get("/api/auth/me", () => {
    return HttpResponse.json({
      id: "1",
      email: "test@example.com",
      full_name: "Test User",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });
  }),

  http.post("/api/auth/logout", () => {
    return new HttpResponse(null, { status: 200 });
  }),

  http.post("/api/auth/refresh", () => {
    return new HttpResponse(null, { status: 401 });
  }),

  // Items handlers
  http.get("/api/items", ({ request }) => {
    const url = new URL(request.url);
    const search = url.searchParams.get("search");

    const items = [
      {
        id: "1",
        name: "Test Item",
        quantity: 10,
        unit: "pcs",
        category_id: "1",
        location_id: "1",
        min_quantity: 2,
        brand: "Test Brand",
        added_date: new Date().toISOString(),
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ];

    if (search && search !== "null") {
      const filtered = items.filter(
        (item) =>
          item.name.toLowerCase().includes(search.toLowerCase()) ||
          item.brand.toLowerCase().includes(search.toLowerCase()),
      );
      return HttpResponse.json({ items: filtered, total: filtered.length });
    }

    return HttpResponse.json({ items, total: items.length });
  }),

  http.get("/api/stats/overview", () => {
    return HttpResponse.json({
      total_items: 1,
      total_locations: 1,
      expiring_soon: 0,
      expired: 0,
      low_stock: 0,
    });
  }),

  http.get("/api/items/:id", () => {
    return HttpResponse.json({
      id: "1",
      name: "Test Item",
      quantity: 10,
      unit: "pcs",
      category_id: "1",
      location_id: "1",
      min_quantity: 2,
      brand: "Test Brand",
      added_date: new Date().toISOString(),
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });
  }),

  http.post("/api/items", async ({ request }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json(
      {
        id: Math.random().toString(36).substr(2, 9),
        ...data,
        added_date: new Date().toISOString(),
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      { status: 201 },
    );
  }),

  http.put("/api/items/:id", async ({ request, params }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({
      id: params.id,
      ...data,
      updated_at: new Date().toISOString(),
    });
  }),

  http.delete("/api/items/:id", () => {
    return new HttpResponse(null, { status: 204 });
  }),

  http.get("/api/categories", () => {
    return HttpResponse.json(
      onePage([
        { id: "1", name: "Food", sort_order: 1 },
        { id: "2", name: "Drinks", sort_order: 2 },
      ]),
    );
  }),

  http.get("/api/items/:id/attachments", () => {
    return HttpResponse.json(onePage([]));
  }),

  // Storages handlers
  http.get("/api/storages", () => {
    return HttpResponse.json([
      {
        id: "1",
        name: "Main Pantry",
        description: "Main storage",
        location_type_id: "1",
      },
    ]);
  }),

  http.get("/api/storage-types", () => {
    return HttpResponse.json([
      { id: "1", name: "Pantry", type_code: "PANTRY", icon: "📦" },
      { id: "2", name: "Fridge", type_code: "FRIDGE", icon: "❄️" },
    ]);
  }),

  http.get("/api/storages/:id", ({ params }) => {
    return HttpResponse.json({
      id: params.id,
      name: "Main Pantry",
      description: "Main storage",
      location_type_id: "1",
      location_type: {
        id: "1",
        name: "Pantry",
        type_code: "PANTRY",
        icon: "📦",
      },
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });
  }),

  // Shopping Lists handlers
  http.get("/api/shopping-lists", () => {
    return HttpResponse.json(
      onePage([
        {
          id: "1",
          name: "Zakupy tygodniowe",
          organization_id: "1",
          is_active: true,
          created_by: "1",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          items: [],
        },
      ]),
    );
  }),

  http.post("/api/shopping-lists", async ({ request }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json(
      {
        id: Math.random().toString(36).substr(2, 9),
        name: data.name || "New List",
        organization_id: "1",
        is_active: true,
        created_by: "1",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        items: [],
      },
      { status: 201 },
    );
  }),

  http.get("/api/organizations/my", () => {
    return HttpResponse.json({
      id: "1",
      name: "Test Organization",
      created_at: new Date().toISOString(),
      created_by: "1",
      enabled_modules: ["core"],
      settings: {},
    });
  }),

  http.get("/api/shopping-lists/:id", () => {
    return HttpResponse.json({
      id: "1",
      name: "Zakupy tygodniowe",
      organization_id: "1",
      is_active: true,
      created_by: "1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      items: [],
    });
  }),

  http.post("/api/shopping-lists/:id/items", async ({ request }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json(
      {
        id: Math.random().toString(36).substr(2, 9),
        shopping_list_id: "1",
        ...data,
        is_purchased: false,
        purchased_at: null,
        purchased_by: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      { status: 201 },
    );
  }),

  // Modules handlers
  http.get("/api/modules/my", () => {
    return HttpResponse.json([
      "core",
      "items",
      "locations",
      "categories",
      "vision",
      "statistics",
      "stock_takes",
      "shopping_lists",
    ]);
  }),

  http.get("/api/modules/available", () => {
    return HttpResponse.json(
      onePage([
        {
          name: "core",
          display_name: "Core",
          description: "Basic features",
          icon: "📦",
          version: "1.0.0",
          requires: [],
          requires_api_key: false,
        },
        {
          name: "vision",
          display_name: "Vision AI",
          description: "Image recognition",
          icon: "👁️",
          version: "1.0.0",
          requires: [],
          requires_api_key: false,
        },
      ]),
    );
  }),

  // Labels handlers
  http.get("/api/labels/pool/stats", () => {
    return HttpResponse.json({ total: 100, assigned: 25, unassigned: 75 });
  }),

  // UoM handlers
  http.get("/api/uoms", () => {
    return HttpResponse.json(
      onePage([
        {
          id: "1",
          category_id: "1",
          name: "Gram",
          symbol: "g",
          factor: 1.0,
          is_reference: true,
        },
        {
          id: "2",
          category_id: "1",
          name: "Kilogram",
          symbol: "kg",
          factor: 1000.0,
          is_reference: false,
        },
        {
          id: "3",
          category_id: "2",
          name: "Piece",
          symbol: "pcs",
          factor: 1.0,
          is_reference: true,
        },
      ]),
    );
  }),

  http.get("/api/uoms/categories", () => {
    return HttpResponse.json(
      onePage([
        {
          id: "1",
          name: "Weight",
          uoms: [
            {
              id: "1",
              category_id: "1",
              name: "Gram",
              symbol: "g",
              factor: 1.0,
              is_reference: true,
            },
            {
              id: "2",
              category_id: "1",
              name: "Kilogram",
              symbol: "kg",
              factor: 1000.0,
              is_reference: false,
            },
          ],
        },
        {
          id: "2",
          name: "Count",
          uoms: [
            {
              id: "3",
              category_id: "2",
              name: "Piece",
              symbol: "pcs",
              factor: 1.0,
              is_reference: true,
            },
          ],
        },
      ]),
    );
  }),

  // Announcements handlers
  http.get("/api/announcements/active", () => {
    return HttpResponse.json(onePage([]));
  }),

  // Notifications handlers
  http.get("/api/notifications", () => {
    return HttpResponse.json({ notifications: [], total: 0 });
  }),

  // Root/Version handler
  http.get("/api/", () => {
    return HttpResponse.json({ version: "1.0.0", message: "Inventari API" });
  }),

  // ────────────────────────────────────────────────────────────────
  // /api/v1/* handlers (duplicates with v1 prefix for app compatibility)
  // ────────────────────────────────────────────────────────────────

  http.post("/api/v1/auth/login", () => {
    return HttpResponse.json({
      access_token: "mocked_access_token",
      token_type: "bearer",
    });
  }),

  http.get("/api/v1/auth/me", () => {
    return HttpResponse.json({
      id: "1",
      email: "test@example.com",
      full_name: "Test User",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });
  }),

  http.post("/api/v1/auth/refresh", () => {
    return new HttpResponse(null, { status: 401 });
  }),

  // Every screen that can render before an account exists reads this, and so
  // do the sign-in and email-settings screens. The default is the ordinary
  // installation — initialized, not a demo; a spec that needs a demo
  // overrides it.
  http.get("/api/v1/auth/init-status", () => {
    return HttpResponse.json({
      is_initialized: true,
      is_demo: false,
      demo_inbox_url: null,
    });
  }),

  http.post("/api/v1/auth/logout", () => {
    return new HttpResponse(null, { status: 200 });
  }),

  http.get("/api/v1/items", ({ request }) => {
    const url = new URL(request.url);
    const search = url.searchParams.get("search");

    const items = [
      {
        id: "1",
        name: "Test Item",
        quantity: 10,
        unit: "pcs",
        category_id: "1",
        location_id: "1",
        min_quantity: 2,
        brand: "Test Brand",
        added_date: new Date().toISOString(),
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ];

    if (search && search !== "null") {
      const filtered = items.filter(
        (item) =>
          item.name.toLowerCase().includes(search.toLowerCase()) ||
          item.brand.toLowerCase().includes(search.toLowerCase()),
      );
      return HttpResponse.json({ items: filtered, total: filtered.length });
    }

    return HttpResponse.json({ items, total: items.length });
  }),

  // Whole-set totals for the list footer — mirrors the same fixture
  // rows as the list above so the two can never disagree in a test.
  http.get("/api/v1/items/aggregates", ({ request }) => {
    const url = new URL(request.url);
    const search = url.searchParams.get("search");
    const count =
      search && search !== "null" && !"test item".includes(search.toLowerCase())
        ? 0
        : 1;
    return HttpResponse.json({ count, total_weight: 0, total_value: 0 });
  }),

  // The one count the dashboard heading and the statistics health card
  // read. Served before the ``/items/:id`` catch-all below, which would
  // otherwise answer this path with a record's fields and make the heading
  // count non-numbers.
  http.get("/api/v1/items/attention-counts", () => {
    return HttpResponse.json({
      expired: 0,
      expiring_soon: 0,
      low_stock: 0,
      records: 0,
    });
  }),

  // Ahead of `/items/:id`, which would take "product-templates" for an id.
  // The name field of a create form asks which products contain what is
  // typed; the catalogue holds none unless a test says otherwise.
  http.get("/api/v1/items/product-templates", () => {
    return HttpResponse.json([]);
  }),

  http.get("/api/v1/items/:id", () => {
    return HttpResponse.json({
      id: "1",
      name: "Test Item",
      quantity: 10,
      unit: "pcs",
      category_id: "1",
      location_id: "1",
      min_quantity: 2,
      brand: "Test Brand",
      added_date: new Date().toISOString(),
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });
  }),

  http.post("/api/v1/items", async ({ request }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json(
      {
        id: Math.random().toString(36).substr(2, 9),
        ...data,
        added_date: new Date().toISOString(),
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      { status: 201 },
    );
  }),

  http.put("/api/v1/items/:id", async ({ request, params }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({
      id: params.id,
      ...data,
      updated_at: new Date().toISOString(),
    });
  }),

  http.delete("/api/v1/items/:id", () => {
    return new HttpResponse(null, { status: 204 });
  }),

  http.get("/api/v1/organizations/my", () => {
    return HttpResponse.json({
      id: "1",
      name: "Test Organization",
      created_by: "1",
      currency: "PLN",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });
  }),
  http.put("/api/v1/organizations", async ({ request }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({
      id: "1",
      name: "Test Organization",
      currency: "PLN",
      ...data,
    });
  }),
  http.get("/api/v1/organizations/my/members", () => {
    return HttpResponse.json([
      {
        id: "user-1",
        full_name: "Alice Admin",
        email: "alice@test.com",
        role: "admin",
        is_active: true,
      },
      {
        id: "user-2",
        full_name: "Bob Member",
        email: "bob@test.com",
        role: "member",
        is_active: true,
      },
    ]);
  }),
  http.post("/api/v1/organizations/my/invitation-code", () => {
    return HttpResponse.json({
      code: "INV-12345",
      expires_at: new Date(Date.now() + 86400000).toISOString(),
    });
  }),
  http.post("/api/v1/organizations/my/remove-member/:id", () => {
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("/api/v1/organizations/current/defaults", () => {
    return HttpResponse.json({ created: 3 });
  }),

  http.get("/api/v1/modules/available", () => {
    return HttpResponse.json(
      onePage([
        {
          name: "core",
          display_name: "Core",
          description: "Core module",
          icon: "package",
          is_default: true,
        },
        {
          name: "recipes",
          display_name: "Recipes",
          description: "Recipe management",
          icon: "chef-hat",
          is_default: false,
        },
      ]),
    );
  }),
  http.post("/api/v1/modules/toggle", () => {
    return HttpResponse.json({ enabled: true });
  }),

  http.post("/api/v1/locations/hierarchy", async ({ request }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({ id: "new-storage", ...data });
  }),

  http.get("/api/v1/modules/my", () => {
    return HttpResponse.json(["core", "items", "locations", "categories"]);
  }),
  // No printer has announced itself: "Send to printer" stays away. Printing
  // is on in the list shown while the real one loads, so any screen with
  // that button asks.
  http.get("/api/v1/printing/agents", () => HttpResponse.json(onePage([]))),
  http.get("/api/v1/modules/focus", () => {
    return HttpResponse.json({
      applied: false,
      focus_module: null,
      enabled_modules: ["core", "items", "locations", "categories"],
      diff: null,
    });
  }),

  // ── Stats ──────────────────────────────────────────────────────
  http.get("/api/v1/stats/config", () => {
    // The module toggles the interface reads at stats:read level — the
    // statistics screen and the stock-value surfaces outside it. Defaults
    // mirror the backend's (both on).
    return HttpResponse.json({
      enable_analytics: true,
      show_inventory_value: true,
    });
  }),
  http.get("/api/v1/stats/overview", () => {
    return HttpResponse.json({
      total_items: 5,
      total_locations: 2,
      expiring_soon: 1,
      expired: 0,
      low_stock: 0,
      currency: "PLN",
    });
  }),
  http.get("/api/v1/stats/low-stock", () => {
    return HttpResponse.json(onePage([]));
  }),
  http.get("/api/v1/stats/by-location", () => {
    return HttpResponse.json(
      onePage([{ location_name: "Fridge", items_count: 3, total_value: 30.0 }]),
    );
  }),
  http.get("/api/v1/stats/by-category", () => {
    return HttpResponse.json(
      onePage([{ category_name: "Dairy", items_count: 2, total_value: 20.0 }]),
    );
  }),
  http.get("/api/v1/stats/expiry-forecast", () => {
    return HttpResponse.json([]);
  }),
  http.get("/api/v1/stats/cost-analysis", () => {
    return HttpResponse.json({
      total_spent: 100,
      total_wasted: 10,
      waste_event_rate: 10,
      savings_opportunities: [],
    });
  }),
  http.get("/api/v1/stats/rotation-analysis", () => {
    return HttpResponse.json({
      fast_moving: [],
      slow_moving: [],
      never_used: [],
    });
  }),
  http.get("/api/v1/stats/smart-alerts", () => {
    return HttpResponse.json({ alerts: [] });
  }),
  http.get("/api/v1/stats/expense-forecast", () => {
    return HttpResponse.json({ forecast: [], total_forecast: 0 });
  }),
  http.get("/api/v1/stats/purchase-patterns", () => {
    return HttpResponse.json({ patterns: [] });
  }),

  // ── Storages ───────────────────────────────────────────────────
  http.get("/api/v1/locations", () => {
    return HttpResponse.json(
      onePage([
        {
          id: "1",
          name: "Kitchen",
          description: null,
          parent_id: null,
          context_schema: [],
          field_definitions: [],
          items_count: 5,
          short_code: "KIT-001",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          organization_id: "org1",
        },
      ]),
    );
  }),
  http.get("/api/v1/locations/tree", () => {
    return HttpResponse.json([
      {
        id: "1",
        name: "Home",
        parent_id: null,
        items_count: 10,
        short_code: "HOM-001",
        children: [
          {
            id: "2",
            name: "Kitchen",
            parent_id: "1",
            items_count: 5,
            short_code: "KIT-001",
            children: [],
          },
        ],
      },
    ]);
  }),
  http.get("/api/v1/locations/:id/items", () => {
    return HttpResponse.json(onePage([]));
  }),
  http.get("/api/v1/locations/:id/summary", ({ params }) => {
    return HttpResponse.json({
      id: params.id,
      name: "Kitchen",
      items_count: 5,
      subtree_items_count: 5,
    });
  }),
  http.get("/api/v1/locations/:id/breadcrumb", () => {
    return HttpResponse.json([]);
  }),
  http.get("/api/v1/locations/:id", ({ params }) => {
    return HttpResponse.json({
      id: params.id,
      name: "Kitchen",
      description: null,
      parent_id: null,
      context_schema: [],
      field_definitions: [],
      items_count: 5,
      short_code: "KIT-001",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      organization_id: "org1",
    });
  }),
  http.post("/api/v1/locations", async ({ request }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({ id: "new-1", ...data }, { status: 201 });
  }),
  http.post("/api/v1/locations/reorg", () => {
    return HttpResponse.json({
      applied: true,
      created: {},
      rejections: [],
    });
  }),
  http.put("/api/v1/locations/:id", async ({ request, params }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({ id: params.id, ...data });
  }),
  http.delete("/api/v1/locations/:id", () => {
    return new HttpResponse(null, { status: 204 });
  }),
  http.get("/api/v1/location-types", () => {
    return HttpResponse.json(
      onePage([
        { id: "1", name: "Pantry", type_code: "PANTRY", icon: "📦" },
        { id: "2", name: "Fridge", type_code: "FRIDGE", icon: "❄️" },
      ]),
    );
  }),

  // ── Categories ─────────────────────────────────────────────────
  http.get("/api/v1/categories", () => {
    return HttpResponse.json(
      onePage([
        { id: "1", name: "Food", sort_order: 1 },
        { id: "2", name: "Drinks", sort_order: 2 },
      ]),
    );
  }),
  http.post("/api/v1/categories", async ({ request }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({ id: "new-cat", ...data }, { status: 201 });
  }),
  http.put("/api/v1/categories/:id", async ({ request, params }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({ id: params.id, ...data });
  }),
  http.delete("/api/v1/categories/:id", () => {
    return new HttpResponse(null, { status: 204 });
  }),

  // ── UoMs ───────────────────────────────────────────────────────
  http.get("/api/v1/uoms/categories", () => {
    return HttpResponse.json(
      onePage([
        {
          id: "1",
          name: "Weight",
          uoms: [
            {
              id: "1",
              category_id: "1",
              name: "Gram",
              symbol: "g",
              factor: 1.0,
              is_reference: true,
            },
            {
              id: "2",
              category_id: "1",
              name: "Kilogram",
              symbol: "kg",
              factor: 1000.0,
              is_reference: false,
            },
          ],
        },
        {
          id: "2",
          name: "Count",
          uoms: [
            {
              id: "3",
              category_id: "2",
              name: "Piece",
              symbol: "pcs",
              factor: 1.0,
              is_reference: true,
            },
          ],
        },
      ]),
    );
  }),
  http.get("/api/v1/uoms", () => {
    return HttpResponse.json(
      onePage([
        {
          id: "1",
          category_id: "1",
          name: "Gram",
          symbol: "g",
          factor: 1.0,
          is_reference: true,
        },
        {
          id: "2",
          category_id: "1",
          name: "Kilogram",
          symbol: "kg",
          factor: 1000.0,
          is_reference: false,
        },
        {
          id: "3",
          category_id: "2",
          name: "Piece",
          symbol: "pcs",
          factor: 1.0,
          is_reference: true,
        },
      ]),
    );
  }),

  // ── Labels ─────────────────────────────────────────────────────
  http.get("/api/v1/labels/pool", () => {
    return HttpResponse.json({
      items: [
        {
          id: "1",
          short_code: "STM-0001",
          description: null,
          is_assigned: false,
          printed_at: null,
          is_item_deleted: false,
          label_type: "GENERIC",
          created_at: new Date().toISOString(),
        },
        {
          id: "2",
          short_code: "STM-0002",
          description: "Fridge label",
          is_assigned: true,
          printed_at: new Date().toISOString(),
          is_item_deleted: false,
          label_type: "GENERIC",
          created_at: new Date().toISOString(),
        },
      ],
      total: 2,
      limit: null,
      offset: 0,
      has_more: false,
    });
  }),
  http.delete("/api/v1/labels/pool/:id", () => {
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("/api/v1/labels/pool/:shortCode/unassign", () => {
    return HttpResponse.json({ message: "Label unassigned" });
  }),
  http.post("/api/v1/labels/pool/generate", async ({ request }) => {
    const data = (await request.json()) as Record<string, unknown>;
    const count = typeof data.count === "number" ? data.count : 1;
    return HttpResponse.json(
      Array.from({ length: count }, (_, i) => ({
        id: `new-${i}`,
        short_code: `STM-NEW-${i}`,
        label_type: data.label_type || "GENERIC",
        is_assigned: false,
        printed_at: null,
        is_item_deleted: false,
        description: null,
        created_at: new Date().toISOString(),
      })),
      { status: 201 },
    );
  }),

  // ── Stock Takes ────────────────────────────────────────────────
  http.get("/api/v1/stock-takes", () => {
    return HttpResponse.json(
      onePage([
        {
          id: "st-1",
          name: "Monthly Check",
          status: "in_progress",
          location_name: "Kitchen",
          items_count: 5,
          counted_items_count: 3,
          progress_percent: 60,
          discrepancies_count: 0,
          started_at: new Date().toISOString(),
        },
      ]),
    );
  }),
  http.get("/api/v1/stock-takes/:id", ({ params }) => {
    return HttpResponse.json({
      id: params.id,
      name: "Monthly Check",
      status: "in_progress",
      location_id: "1",
      location_name: "Kitchen",
      items_count: 2,
      items: [
        {
          id: "sti-1",
          item_id: "1",
          name: "Test Item",
          system_quantity: 5,
          counted_quantity: null,
        },
      ],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });
  }),
  http.post("/api/v1/stock-takes", async ({ request }) => {
    const data = (await request.json()) as Record<string, unknown>;
    // Explicit fields instead of `...data` echo: the real backend persists
    // the creation options (blind_mode, tolerance_percent,
    // require_full_count), so the mock mirrors that contract. Tests must
    // assert response fields, not the request echo.
    return HttpResponse.json(
      {
        id: "new-st",
        user_id: "1",
        location_id: data.location_id,
        name: data.name,
        description: data.description ?? null,
        notes: data.notes ?? null,
        status: "in_progress",
        blind_mode: data.blind_mode ?? false,
        tolerance_percent: data.tolerance_percent ?? null,
        require_full_count: data.require_full_count ?? true,
        started_at: new Date().toISOString(),
        completed_at: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        items_count: 0,
        counted_items_count: 0,
        discrepancies_count: 0,
      },
      { status: 201 },
    );
  }),
  http.delete("/api/v1/stock-takes/:id", () => {
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("/api/v1/stock-takes/:id/items", async ({ request }) => {
    const data = (await request.json()) as Record<string, unknown>;
    // The real backend rejects duplicates with 409
    // STOCK_TAKE_ITEM_ALREADY_EXISTS. item_id "1" is the item already
    // listed by the detail mock above.
    if (data.item_id === "1") {
      return HttpResponse.json(
        {
          detail: {
            code: "STOCK_TAKE_ITEM_ALREADY_EXISTS",
            message: "Item already exists in stock take",
          },
        },
        { status: 409 },
      );
    }
    return HttpResponse.json({ id: "sti-new", ...data }, { status: 201 });
  }),
  http.patch(
    "/api/v1/stock-takes/:id/items/:itemId/count",
    async ({ request, params }) => {
      const data = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({
        id: params.itemId,
        stock_take_id: params.id,
        item_id: "1",
        item_name: "Test Item",
        item_brand: null,
        uom_symbol: null,
        system_quantity: 5,
        counted_quantity: data.counted_quantity,
        shelf_location: data.shelf_location ?? null,
        notes: data.notes ?? null,
        discrepancy_reason: null,
        is_discrepancy: 0,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
    },
  ),
  http.post("/api/v1/stock-takes/:id/complete", () => {
    return HttpResponse.json({ status: "COMPLETED" });
  }),
  http.patch("/api/v1/stock-takes/:id/status", async ({ request, params }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({ id: params.id, status: data.status });
  }),

  // ── Webhooks ───────────────────────────────────────────────────
  http.get("/api/v1/webhooks/endpoints", () => {
    return HttpResponse.json(onePage([]));
  }),
  http.get("/api/v1/webhooks/events", () => {
    return HttpResponse.json(["item.created", "item.updated", "item.deleted"]);
  }),
  http.post("/api/v1/webhooks/endpoints", async ({ request }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({ id: "new-wh", ...data }, { status: 201 });
  }),
  http.put("/api/v1/webhooks/endpoints/:id", async ({ request, params }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({ id: params.id, ...data });
  }),
  http.delete("/api/v1/webhooks/endpoints/:id", () => {
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("/api/v1/webhooks/endpoints/:id/test", () => {
    return HttpResponse.json({ status: "success" });
  }),
  http.post("/api/v1/webhooks/endpoints/:id/reactivate", () => {
    return HttpResponse.json({ is_active: true });
  }),
  http.get("/api/v1/webhooks/endpoints/:id/deliveries", () => {
    return HttpResponse.json({ items: [], total: 0 });
  }),

  // ── Items history ──────────────────────────────────────────────
  http.get("/api/v1/items/history", () => {
    return HttpResponse.json([]);
  }),

  // The catalogue knows none of these products unless a test says otherwise:
  // the item form asks before it saves, so the default answer is "no match"
  // rather than an unhandled request.
  // A product the catalogue does not know is answered `null`, not a 404.
  http.get("/api/v1/items/product-templates/lookup", () => {
    return HttpResponse.json(null);
  }),

  // An empty list asks whether the catalogue holds products with no stock;
  // by default it holds none, so the list invites the first product.
  http.get("/api/v1/items/product-templates/count", () => {
    return HttpResponse.json({ count: 0 });
  }),

  // ── Notifications ─────────────────────────────────────────────
  http.get("/api/v1/notifications", () => {
    return HttpResponse.json(
      onePage([
        {
          id: "n1",
          type: "info",
          title: "Welcome",
          content: "Welcome to Inventari",
          is_read: false,
          created_at: new Date().toISOString(),
        },
        {
          id: "n2",
          type: "warning",
          title: "Expiry alert",
          content: "Item expires soon",
          is_read: true,
          created_at: new Date().toISOString(),
          link: "/items/1",
        },
      ]),
    );
  }),
  http.patch("/api/v1/notifications/:id", () => {
    return HttpResponse.json({ id: "n1", is_read: true });
  }),
  http.post("/api/v1/notifications/read-all", () => {
    return new HttpResponse(null, { status: 204 });
  }),
  http.delete("/api/v1/notifications/:id", () => {
    return new HttpResponse(null, { status: 204 });
  }),

  // ── Shopping lists (active) ───────────────────────────────────
  http.get("/api/v1/shopping-lists/active", () => {
    return HttpResponse.json(null);
  }),
  http.get("/api/v1/shopping-lists", () => {
    return HttpResponse.json(onePage([]));
  }),
  // The replenish engine has nothing to propose by default. A test that
  // needs the dashboard's door open overrides this with `server.use`.
  http.get("/api/v1/shopping-lists/suggestions", () => {
    return HttpResponse.json({ suggestions: [] });
  }),

  // ── Recipes ───────────────────────────────────────────────────
  // Collection routes must be registered before the dynamic /recipes/:id
  // handler, otherwise "collections" would be captured as an id.
  http.get("/api/v1/recipes/collections", () => {
    return HttpResponse.json(onePage([]));
  }),
  http.post("/api/v1/recipes/collections", async ({ request }) => {
    const body = (await request.json()) as { name: string; icon?: string };
    return HttpResponse.json(
      {
        id: "collection-test-1",
        name: body.name,
        icon: body.icon ?? null,
        parent_id: null,
        recipe_count: 0,
        children: [],
      },
      { status: 201 },
    );
  }),
  http.put("/api/v1/recipes/collections/:id", async ({ request }) => {
    const body = (await request.json()) as { name: string };
    return HttpResponse.json({
      id: "collection-test-1",
      name: body.name,
      icon: null,
      parent_id: null,
      recipe_count: 0,
      children: [],
    });
  }),
  http.delete("/api/v1/recipes/collections/:id", () => {
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("/api/v1/recipes/collections/:id/recipes", () => {
    return HttpResponse.json(
      { collection_id: "collection-test-1", recipe_id: "recipe-1" },
      { status: 201 },
    );
  }),
  http.delete("/api/v1/recipes/collections/:id/recipes/:recipeId", () => {
    return new HttpResponse(null, { status: 204 });
  }),
  http.get("/api/v1/recipes/available", () => {
    return HttpResponse.json(onePage([]));
  }),
  http.get("/api/v1/recipes/:id/availability", ({ params }) => {
    return HttpResponse.json({
      can_cook: true,
      missing: [],
      recipe_id: params.id,
      servings: 2,
      ingredients: [],
    });
  }),
  http.get("/api/v1/recipes/:id/nutrition", () => {
    return HttpResponse.json(null);
  }),
  http.get("/api/v1/recipes/:id/cost", () => {
    return HttpResponse.json({
      total_cost: 0,
      cost_per_serving: 0,
      servings: 1,
      ingredients: [],
      currency: "PLN",
    });
  }),
  http.get("/api/v1/recipes/:id/history", () => {
    return HttpResponse.json(onePage([]));
  }),
  http.get("/api/v1/recipes/tags", () => {
    return HttpResponse.json(onePage([]));
  }),
  http.get("/api/v1/recipes/:id", ({ params }) => {
    return HttpResponse.json({
      id: params.id,
      name: "Pasta Carbonara",
      description: "Classic Italian pasta",
      instructions: "Cook pasta. Mix eggs. Combine.",
      servings: 2,
      prep_time: 20,
      cook_time: 10,
      tags: [],
      is_favorite: false,
      ingredients: [],
      image_url: null,
      created_at: new Date().toISOString(),
    });
  }),
  http.get("/api/v1/recipes", () => {
    return HttpResponse.json({
      items: [
        {
          id: "1",
          name: "Pasta Carbonara",
          tags: [],
          is_favorite: false,
          servings: 2,
          prep_time: 20,
          cook_time: 10,
          ingredients_count: 4,
          image_url: null,
          created_at: new Date().toISOString(),
        },
        {
          id: "2",
          name: "Caesar Salad",
          tags: [],
          is_favorite: true,
          servings: 4,
          prep_time: 15,
          cook_time: 0,
          ingredients_count: 5,
          image_url: null,
          created_at: new Date().toISOString(),
        },
      ],
      total: 2,
      limit: 50,
      offset: 0,
      has_more: false,
    });
  }),
  http.post("/api/v1/recipes", async ({ request }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json(
      {
        id: "new-1",
        ...data,
        ingredients: [],
        tags: [],
        is_favorite: false,
        created_at: new Date().toISOString(),
      },
      { status: 201 },
    );
  }),
  http.put("/api/v1/recipes/:id", async ({ request, params }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({
      id: params.id,
      name: "Updated Recipe",
      ...data,
      ingredients: [],
      tags: [],
      is_favorite: false,
    });
  }),
  http.delete("/api/v1/recipes/:id", () => {
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("/api/v1/recipes/:id/start-picking", () => {
    return HttpResponse.json({
      session_id: "session-1",
      recipe_id: "1",
      items: [],
    });
  }),
  http.post("/api/v1/recipes/:id/add-to-shopping-list", () => {
    return HttpResponse.json({ added: 1 });
  }),
  http.patch("/api/v1/recipes/:id/history/:historyId", () => {
    return HttpResponse.json({ id: "h1", rating: 5, notes: "" });
  }),
  http.post("/api/v1/recipes/:id/image", () => {
    return HttpResponse.json({ image_url: "/uploads/recipe.jpg" });
  }),
  http.delete("/api/v1/recipes/:id/image", () => {
    return new HttpResponse(null, { status: 204 });
  }),

  // ── Cloud Admin ───────────────────────────────────────────────
  http.get("/api/v1/inventari-cloud/admin/organizations", () => {
    return HttpResponse.json([
      {
        id: "org1",
        name: "Test Org",
        member_count: 2,
        waste_count: 0,
        activity_30d: 10,
        allowed_modules: [],
        members: [],
      },
    ]);
  }),
  http.get("/api/v1/inventari-cloud/admin/stats", () => {
    return HttpResponse.json({ total_orgs: 1, total_users: 2, active_30d: 1 });
  }),
  http.get("/api/v1/inventari-cloud/admin/all-modules", () => {
    return HttpResponse.json([{ name: "recipes", display_name: "Recipes" }]);
  }),
  http.get("/api/v1/inventari-cloud/admin/ai-usage", () => {
    return HttpResponse.json({
      total_requests: 0,
      total_tokens: 0,
      by_day: [],
    });
  }),
  http.get("/api/v1/inventari-cloud/admin/system-settings", () => {
    return HttpResponse.json({});
  }),
  http.put(
    "/api/v1/inventari-cloud/admin/organizations/:id/modules",
    async ({ request, params }) => {
      const data = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({ org_id: params.id, ...data });
    },
  ),

  // ── Approvals ──────────────────────────────────────────────────
  // The default install has a workflow, so the request affordance is the
  // button wherever a test is not about the missing-workflow state; those
  // override this with `server.use`. The list below still answers `[]`, as
  // the filtered list does for an account without the read grant.
  http.get("/api/v1/approvals/workflows/configured", () => {
    return HttpResponse.json({ configured: true });
  }),
  http.get("/api/v1/approvals/workflows", () => {
    return HttpResponse.json(onePage([]));
  }),
  http.post("/api/v1/approvals/workflows", async ({ request }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({ id: "wf-new", ...data }, { status: 201 });
  }),
  http.patch("/api/v1/approvals/workflows/:id", async ({ request, params }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({ id: params.id, ...data });
  }),
  http.delete("/api/v1/approvals/workflows/:id", () => {
    return new HttpResponse(null, { status: 204 });
  }),
  http.get("/api/v1/approvals/requests", () => {
    return HttpResponse.json({
      items: [],
      total: 0,
      limit: 100,
      offset: 0,
      has_more: false,
    });
  }),
  http.post("/api/v1/approvals/requests", async ({ request }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json(
      { id: "req-new", status: "PENDING", ...data },
      { status: 201 },
    );
  }),
  http.post("/api/v1/approvals/requests/:id/approve", () => {
    return HttpResponse.json({ id: "req-1", status: "APPROVED" });
  }),
  http.post("/api/v1/approvals/requests/:id/reject", () => {
    return HttpResponse.json({ id: "req-1", status: "REJECTED" });
  }),

  // ── API Keys ──────────────────────────────────────────────────
  http.get("/api/v1/api-keys", () => {
    return HttpResponse.json(onePage([]));
  }),
  http.post("/api/v1/api-keys", async ({ request }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json(
      { id: "key-new", key_prefix: "inv_abc", raw_key: "inv_abc123", ...data },
      { status: 201 },
    );
  }),
  http.delete("/api/v1/api-keys/:id", () => {
    return new HttpResponse(null, { status: 204 });
  }),

  // -- Equipment Module --
  // The shape of `EquipmentDashboard` in the API contract, held there by
  // `satisfies`. A mock with fields the endpoint does not return, or without
  // the lists the widget reads, crashes the equipment widget into the module
  // error boundary — which a slower test runner reaches before the test ends.
  http.get("/api/v1/equipment/dashboard", () => {
    return HttpResponse.json({
      total_assets: 0,
      active_assignments: 0,
      in_maintenance: 0,
      retired: 0,
      by_status: {},
      by_category: [],
      recent_activity: [],
      warranty_alerts: [],
      expired_warranty_alerts: [],
    } satisfies components["schemas"]["EquipmentDashboard"]);
  }),
  http.get("/api/v1/equipment/assignments", () => {
    return HttpResponse.json([]);
  }),
  http.post("/api/v1/equipment/assignments", async ({ request }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({ id: "assign-1", ...data });
  }),
  http.post(
    "/api/v1/equipment/assignments/:id/checkin",
    async ({ request }) => {
      const data = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({ id: "assign-1", ...data });
    },
  ),
  http.get("/api/v1/equipment/assignments/item/:itemId", () => {
    return HttpResponse.json(onePage([]));
  }),
  http.get("/api/v1/equipment/warranty-alerts", () => {
    return HttpResponse.json(onePage([]));
  }),
  http.post("/api/v1/equipment/maintenance", async ({ request }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({ id: "maint-1", ...data });
  }),
  http.get("/api/v1/equipment/maintenance/item/:itemId", () => {
    return HttpResponse.json(onePage([]));
  }),
  http.put("/api/v1/equipment/maintenance/:logId", async ({ request }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({ id: "maint-1", ...data });
  }),
  http.delete("/api/v1/equipment/maintenance/:logId", () => {
    return HttpResponse.json({ ok: true });
  }),
  http.get("/api/v1/equipment/templates", () => {
    return HttpResponse.json(onePage([]));
  }),
  http.get("/api/v1/equipment/templates/:id", () => {
    return HttpResponse.json({});
  }),
  http.post("/api/v1/equipment/templates", async ({ request }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({ id: "tmpl-1", ...data });
  }),
  http.put("/api/v1/equipment/templates/:id", async ({ request }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({ id: "tmpl-1", ...data });
  }),
  http.delete("/api/v1/equipment/templates/:id", () => {
    return HttpResponse.json({ ok: true });
  }),
  http.post("/api/v1/equipment/templates/seed-defaults", () => {
    return HttpResponse.json({ seeded: true });
  }),
  http.get("/api/v1/equipment/protocol/placeholders", () => {
    return HttpResponse.json([]);
  }),
  http.get("/api/v1/equipment/assignments/:id/protocol/html", () => {
    return HttpResponse.text("<html><body>Protocol</body></html>");
  }),
  http.get("/api/v1/equipment/assignments/:id/protocol/pdf", () => {
    return new HttpResponse(new ArrayBuffer(8), {
      headers: { "Content-Type": "application/pdf" },
    });
  }),
  http.post("/api/v1/equipment/items/bulk", async ({ request }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({ created: 0, errors: [], ...data });
  }),
  http.get("/api/v1/equipment/campaigns", () => {
    return HttpResponse.json(onePage([]));
  }),
  http.get("/api/v1/equipment/campaigns/:id", () => {
    return HttpResponse.json({});
  }),
  http.post("/api/v1/equipment/campaigns", async ({ request }) => {
    const data = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({ id: "camp-1", ...data });
  }),
  http.post("/api/v1/equipment/campaigns/:id/launch", () => {
    return HttpResponse.json({ launched: true });
  }),
  http.post("/api/v1/equipment/campaigns/:id/remind", () => {
    return HttpResponse.json({ reminded: true });
  }),
  http.post("/api/v1/equipment/campaigns/:id/complete", () => {
    return HttpResponse.json({ completed: true });
  }),

  // ── Incidental background queries ─────────────────────────────
  // Components fire these on mount regardless of what a given test asserts
  // (RBAC/AI settings, dashboard widgets, hook shape tests). Empty defaults
  // keep the MSW catch-all quiet; tests that care override via server.use().
  http.get("/api/v1/users/org-members", () => {
    return HttpResponse.json(onePage([]));
  }),
  http.get("/api/v1/roles", () => {
    return HttpResponse.json(onePage([]));
  }),
  http.get("/api/v1/ai-connections", () => {
    return HttpResponse.json(onePage([]));
  }),
  http.get("/api/v1/ai-connections/purposes", () => {
    return HttpResponse.json(onePage([]));
  }),
  http.get("/api/v1/equipment/assignments/overdue", () => {
    return HttpResponse.json({ items: [], total: 0 });
  }),
  http.get("/api/v1/recipes/meal-plans/exclusions", () => {
    return HttpResponse.json(onePage([]));
  }),
  http.get("/api/v1/locations/:id/print", () => {
    return new HttpResponse(
      new Blob(["%PDF-mock"], { type: "application/pdf" }),
    );
  }),
  http.get("/api/v1/warehouse/documents/doc-1", () => {
    return HttpResponse.json({
      id: "doc-1",
      doc_number: "IN-0001",
      doc_type: "IN",
      status: "DRAFT",
      lines: [],
    });
  }),
];

// Ambient endpoints — shared hooks fire these on mount while tests assert
// something unrelated, so the catch-all below used to 500 them ~90 times per
// run and every run spammed "unmocked request" errors. A valid empty response
// keeps those components on their normal path (the shapes mirror the API
// contracts); tests that assert on these endpoints mock their own handlers
// via server.use().
handlers.push(
  http.get("/api/v1/profiles", () => HttpResponse.json(onePage([]))),
  http.get("/api/v1/equipment/models", () => HttpResponse.json(onePage([]))),
  http.get("/api/v1/equipment/my-assets/history", () =>
    HttpResponse.json(onePage([])),
  ),
  http.get("/api/v1/equipment/assets", () =>
    HttpResponse.json({ items: [], total: 0 }),
  ),
  http.get("/api/v1/equipment/valuation", () =>
    HttpResponse.json({
      total_purchase_value: 0,
      total_book_value: 0,
      total_depreciation: 0,
      by_category: [],
      asset_count: 0,
      depreciable_count: 0,
      excluded_count: 0,
    }),
  ),
  http.get("/api/v1/equipment/:item_id/valuation", () =>
    HttpResponse.json({
      item_id: "item-1",
      item_name: "",
      serial_number: null,
      purchase_price: null,
      book_value: 0,
      depreciation_pct: 0,
      useful_life_years: 0,
      is_depreciable: false,
    }),
  ),
  http.get("/api/v1/purchase-orders/:po_id/approval-requirement", () =>
    HttpResponse.json({ approval_required: false, approval_solvable: true }),
  ),
  http.get("/api/v1/purchase-orders/:po_id/pending-quantities", () =>
    HttpResponse.json({}),
  ),
  http.get("/api/v1/recipes/ingredient-defaults/lookup", ({ request }) => {
    const name = new URL(request.url).searchParams.get("name") ?? "";
    return HttpResponse.json({
      found: false,
      name,
      lang: "en",
      calories_kcal: null,
      protein_g: null,
      fat_g: null,
      carbs_g: null,
    });
  }),
  http.get("/api/v1/warehouse/price-hint", () =>
    HttpResponse.json({ unit_price: null, tax_rate: null, currency: null }),
  ),
  // The carrier field of a dispatch's completion asks for suggestions
  // wherever it is shown; none until a test says otherwise.
  http.get("/api/v1/warehouse/shipments/carriers", () =>
    HttpResponse.json({ carriers: [] }),
  ),
  // Configuration says how each top-level location receives; none chose
  // two steps until a test says otherwise.
  http.get("/api/v1/warehouse/putaway/receiving-modes", () =>
    HttpResponse.json(onePage([])),
  ),
  // Configuration and a product's edit form read the tax rates; the
  // organization keeps none, and its country offers none, until a test says
  // otherwise.
  http.get("/api/v1/warehouse/tax-rates", () => HttpResponse.json(onePage([]))),
  http.get("/api/v1/warehouse/tax-rates/categories", () =>
    HttpResponse.json(onePage([])),
  ),
  http.get("/api/v1/warehouse/tax-rates/country", () =>
    HttpResponse.json({
      country: null,
      rates: [],
      require_partner_tax_id: false,
    }),
  ),
  // A scanning sheet that goes away with its session open pauses it; every
  // test that unmounts one sends this, and only some care.
  http.post(
    "/api/v1/warehouse/documents/:documentId/:direction/:sessionId/pause",
    () => new HttpResponse(null, { status: 204 }),
  ),
  http.post("/api/v1/auth/me/language", () =>
    HttpResponse.json({
      id: "1",
      email: "test@example.com",
      full_name: "Test User",
    }),
  ),
);

// Catch-all handler to immediately fail any unmocked requests
// This prevents JSDOM from making real network connections and hanging the process
handlers.push(
  http.all("*", ({ request }) => {
    console.error(
      `[MSW Catch-All] Unmocked request intercepted: ${request.method} ${request.url}`,
    );
    return HttpResponse.json(
      { error: "Unmocked request in tests" },
      { status: 500 },
    );
  }),
);
