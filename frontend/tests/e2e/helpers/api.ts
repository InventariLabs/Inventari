import { APIRequestContext } from "@playwright/test";

/** Pull a cookie the API set on the request context's own jar. */
export async function cookieValue(
  request: APIRequestContext,
  name: string,
): Promise<string> {
  const { cookies } = await request.storageState();
  const cookie = cookies.find((c) => c.name === name);
  if (!cookie) throw new Error(`Cookie ${name} was not set`);
  return cookie.value;
}

export class ApiHelper {
  constructor(private request: APIRequestContext) {}

  /**
   * Log in and return the body plus the refresh token read from the cookie.
   *
   * The refresh token is HttpOnly-cookie-only — it is not in the
   * response body — but tests that seed a browser context still need its value.
   */
  async login(username: string, password: string, retries = 2) {
    for (let attempt = 0; attempt <= retries; attempt++) {
      const response = await this.request.post("/api/v1/auth/login", {
        form: { username, password },
      });

      if (response.ok()) {
        return {
          ...(await response.json()),
          refresh_token: await cookieValue(this.request, "refresh_token"),
        };
      }

      if (attempt < retries && response.status() >= 500) {
        await new Promise((r) => setTimeout(r, 300 * (attempt + 1)));
        continue;
      }

      // Every spec logs in from its own beforeAll, on one shared account, and
      // /auth/login allows 5 per minute — so a rate-limited backend fails tens
      // of specs with errors that point anywhere but here. Retrying would mean
      // sleeping out the window; say what to do instead.
      if (response.status() === 429) {
        throw new Error(
          `Login rate-limited (429). The backend is enforcing rate limits, ` +
            `which the suite cannot work under: it signs in once per spec on ` +
            `one account. Run the tests through 'make test-e2e' (it restarts ` +
            `the backend with TESTING=true and restores it afterwards), or ` +
            `start the stack yourself with TESTING=true.`,
        );
      }

      throw new Error(
        `Login failed: ${response.status()} ${await response.text()}`,
      );
    }
    throw new Error("Login failed after retries");
  }

  async getMyModules(token: string): Promise<string[]> {
    const response = await this.request.get("/api/v1/modules/my", {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });
    if (response.ok()) {
      return await response.json();
    }
    return [];
  }

  async toggleModule(token: string, module_name: string, enabled: boolean) {
    const response = await this.request.post("/api/v1/modules/toggle", {
      headers: {
        Authorization: `Bearer ${token}`,
      },
      data: {
        module_name,
        enabled,
      },
    });
    return response.ok();
  }

  async setModuleSettings(
    token: string,
    moduleName: string,
    settings: Record<string, unknown>,
  ) {
    const response = await this.request.put(
      `/api/v1/modules/${moduleName}/settings`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: settings,
      },
    );
    if (!response.ok())
      throw new Error(
        `Failed to set ${moduleName} settings: ${await response.text()}`,
      );
  }

  async createItem(
    token: string,
    data: Record<string, unknown>,
  ): Promise<{ id: string }> {
    const response = await this.request.post("/api/v1/items", {
      headers: { Authorization: `Bearer ${token}` },
      data,
    });
    if (!response.ok())
      throw new Error(`Failed to create item: ${await response.text()}`);
    return await response.json();
  }

  async deleteItem(token: string, id: string, reason?: string): Promise<void> {
    const response = await this.request.delete(`/api/v1/items/${id}`, {
      headers: { Authorization: `Bearer ${token}` },
      ...(reason ? { data: { reason } } : {}),
    });
    if (!response.ok() && response.status() !== 404)
      throw new Error(`Failed to delete item: ${await response.text()}`);
  }

  /**
   * The id of a location type that watches expiry, made when the
   * organization has none (a profile without food kinds). A location of such
   * a type is what makes the product list offer its expiring/expired chips
   * without the statistics overview, the other signal they depend on.
   */
  async ensureExpiryStorageType(token: string): Promise<string> {
    const headers = { Authorization: `Bearer ${token}` };
    const find = async (
      match: (type: { type_code: string; behavior_mode: string }) => boolean,
    ): Promise<string | undefined> => {
      const response = await this.request.get(
        "/api/v1/location-types?limit=200",
        { headers },
      );
      if (!response.ok())
        throw new Error(
          `Failed to list storage types: ${await response.text()}`,
        );
      const { items } = (await response.json()) as {
        items: Array<{ id: string; type_code: string; behavior_mode: string }>;
      };
      return items.find(match)?.id;
    };
    const existing = await find(
      (type) =>
        type.behavior_mode === "EXPIRY" || type.behavior_mode === "FREEZING",
    );
    if (existing) return existing;

    // A parallel worker may have created the type a moment ago and not yet
    // switched its mode (create starts a type as STOCK). Whoever loses the
    // create finds it by code and makes the same, idempotent update.
    await this.request.post("/api/v1/location-types", {
      headers,
      data: { name: "E2E Expiry", type_code: "E2E_EXPIRY" },
    });
    const id = await find((type) => type.type_code === "E2E_EXPIRY");
    if (!id) throw new Error("Failed to create the E2E expiry storage type");
    const updated = await this.request.put(`/api/v1/location-types/${id}`, {
      headers,
      data: { behavior_mode: "EXPIRY" },
    });
    if (!updated.ok())
      throw new Error(
        `Failed to set storage type mode: ${await updated.text()}`,
      );
    return id;
  }

  async createStorage(
    token: string,
    data: Record<string, unknown>,
  ): Promise<{ id: string }> {
    const response = await this.request.post("/api/v1/locations", {
      headers: { Authorization: `Bearer ${token}` },
      data,
    });
    if (!response.ok())
      throw new Error(`Failed to create storage: ${await response.text()}`);
    return await response.json();
  }

  async deleteStorage(token: string, id: string): Promise<void> {
    const response = await this.request.delete(`/api/v1/locations/${id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok() && response.status() !== 404)
      throw new Error(`Failed to delete storage: ${await response.text()}`);
  }

  /**
   * Create a storage, falling back to an existing one with the same name on
   * a 409 collision. ``beforeAll`` seed data can collide with a leftover row
   * from a previous attempt (Playwright retries rerun ``beforeAll`` in the
   * same process, so module-level UIDs are stable across retries). Mirrors
   * the idempotent pattern used by ``globalSetup``.
   */
  async createStorageIdempotent(
    token: string,
    data: Record<string, unknown>,
  ): Promise<{ id: string }> {
    try {
      return await this.createStorage(token, data);
    } catch (e) {
      const name = String(data.name ?? "");
      if (name && (e as Error).message?.includes("already exists")) {
        const storages = await this.listStorages(token);
        const existing = storages.find((s) => s.name === name);
        if (existing) return existing;
      }
      throw e;
    }
  }

  async createCategory(
    token: string,
    data: Record<string, unknown>,
  ): Promise<{ id: string }> {
    const response = await this.request.post("/api/v1/categories", {
      headers: { Authorization: `Bearer ${token}` },
      data,
    });
    if (!response.ok())
      throw new Error(`Failed to create category: ${await response.text()}`);
    return await response.json();
  }

  async deleteCategory(token: string, id: string): Promise<void> {
    const response = await this.request.delete(`/api/v1/categories/${id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok() && response.status() !== 404)
      throw new Error(`Failed to delete category: ${await response.text()}`);
  }

  /**
   * Create a category, falling back to an existing one with the same name on
   * a 409 collision. See {@link createStorageIdempotent} for the rationale.
   */
  async createCategoryIdempotent(
    token: string,
    data: Record<string, unknown>,
  ): Promise<{ id: string }> {
    try {
      return await this.createCategory(token, data);
    } catch (e) {
      const name = String(data.name ?? "");
      if (name && (e as Error).message?.includes("already exists")) {
        const cats = await this.listCategories(token);
        const existing = cats.find((c) => c.name === name);
        if (existing) return existing;
      }
      throw e;
    }
  }

  async createShoppingList(
    token: string,
    data: Record<string, unknown>,
  ): Promise<{ id: string }> {
    const response = await this.request.post("/api/v1/shopping-lists", {
      headers: { Authorization: `Bearer ${token}` },
      data,
    });
    if (!response.ok())
      throw new Error(
        `Failed to create shopping list: ${await response.text()}`,
      );
    return await response.json();
  }

  async deleteShoppingList(token: string, id: string): Promise<void> {
    const response = await this.request.delete(`/api/v1/shopping-lists/${id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok() && response.status() !== 404)
      throw new Error(
        `Failed to delete shopping list: ${await response.text()}`,
      );
  }

  async listShoppingLists(
    token: string,
  ): Promise<Array<{ id: string; name?: string; title?: string }>> {
    const response = await this.request.get(
      "/api/v1/shopping-lists?limit=200",
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok()) return [];
    return (await response.json()).items;
  }

  async createRecipe(
    token: string,
    data: Record<string, unknown>,
  ): Promise<{ id: string }> {
    const response = await this.request.post("/api/v1/recipes", {
      headers: { Authorization: `Bearer ${token}` },
      data,
    });
    if (!response.ok())
      throw new Error(`Failed to create recipe: ${await response.text()}`);
    return await response.json();
  }

  async listRecipes(
    token: string,
  ): Promise<Array<{ id: string; name: string }>> {
    const response = await this.request.get("/api/v1/recipes?limit=200", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok())
      throw new Error(`Failed to list recipes: ${await response.text()}`);
    // GET /recipes returns a PaginatedResponse envelope, not a bare array.
    const data = await response.json();
    return Array.isArray(data) ? data : (data.items ?? []);
  }

  async deleteRecipe(token: string, id: string): Promise<void> {
    const response = await this.request.delete(`/api/v1/recipes/${id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok() && response.status() !== 404)
      throw new Error(`Failed to delete recipe: ${await response.text()}`);
  }

  async getRecipe(token: string, id: string): Promise<Record<string, unknown>> {
    const response = await this.request.get(`/api/v1/recipes/${id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok())
      throw new Error(`Failed to get recipe: ${await response.text()}`);
    return await response.json();
  }

  async updateRecipe(
    token: string,
    id: string,
    data: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.put(`/api/v1/recipes/${id}`, {
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      data,
    });
    if (!response.ok())
      throw new Error(`Failed to update recipe: ${await response.text()}`);
    return await response.json();
  }

  async getRecipeNutrition(
    token: string,
    recipeId: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.get(
      `/api/v1/recipes/${recipeId}/nutrition`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(
        `Failed to get recipe nutrition: ${await response.text()}`,
      );
    return await response.json();
  }

  async getRecipeExport(
    token: string,
    recipeId: string,
    format = "json",
  ): Promise<Record<string, unknown>> {
    const response = await this.request.get(
      `/api/v1/recipes/${recipeId}/export?format=${format}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to export recipe: ${await response.text()}`);
    return await response.json();
  }

  async importRecipe(
    token: string,
    data: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.post("/api/v1/recipes/import", {
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      data,
    });
    if (!response.ok())
      throw new Error(`Failed to import recipe: ${await response.text()}`);
    return await response.json();
  }

  async importRecipePreview(
    token: string,
    data: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.post("/api/v1/recipes/import/preview", {
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      data,
    });
    if (!response.ok())
      throw new Error(`Failed to preview import: ${await response.text()}`);
    return await response.json();
  }

  async createWebhook(
    token: string,
    data: Record<string, unknown>,
  ): Promise<{ id: string }> {
    const response = await this.request.post("/api/v1/webhooks/endpoints", {
      headers: { Authorization: `Bearer ${token}` },
      data,
    });
    if (!response.ok())
      throw new Error(`Failed to create webhook: ${await response.text()}`);
    return await response.json();
  }

  async deleteWebhook(token: string, id: string): Promise<void> {
    const response = await this.request.delete(
      `/api/v1/webhooks/endpoints/${id}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok() && response.status() !== 404)
      throw new Error(`Failed to delete webhook: ${await response.text()}`);
  }

  async listWebhooks(
    token: string,
  ): Promise<Array<{ id: string; name: string }>> {
    const response = await this.request.get("/api/v1/webhooks/endpoints", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok()) return [];
    return (await response.json()).items;
  }

  async addShoppingListItem(
    token: string,
    listId: string,
    data: Record<string, unknown>,
  ): Promise<{ id: string }> {
    const response = await this.request.post(
      `/api/v1/shopping-lists/${listId}/items`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data,
      },
    );
    if (!response.ok())
      throw new Error(
        `Failed to add shopping list item: ${await response.text()}`,
      );
    return await response.json();
  }

  async generateLabels(
    token: string,
    count: number,
    prefix = "E2E",
  ): Promise<Array<{ id: string; short_code: string }>> {
    const response = await this.request.post("/api/v1/labels/pool/generate", {
      headers: { Authorization: `Bearer ${token}` },
      data: { count, prefix, label_type: "GENERIC" },
    });
    if (!response.ok())
      throw new Error(`Failed to generate labels: ${await response.text()}`);
    return await response.json();
  }

  async deleteLabel(token: string, labelId: string): Promise<void> {
    const response = await this.request.delete(
      `/api/v1/labels/pool/${labelId}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok() && response.status() !== 404)
      throw new Error(`Failed to delete label: ${await response.text()}`);
  }

  /**
   * Finish first-run onboarding so the API stops bouncing fresh databases
   * to the workflow wizard. Idempotent: 409 (already completed) is fine.
   * ``food_home`` is the profile the E2E organization historically runs on.
   */
  async completeOnboarding(token: string): Promise<void> {
    const response = await this.request.post("/api/v1/onboarding/setup", {
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      data: { profile_id: "food_home" },
    });
    if (!response.ok() && response.status() !== 409)
      throw new Error(
        `Failed to complete onboarding: ${await response.text()}`,
      );
  }

  /**
   * Switches every optional module on, maker included. Only globalSetup and
   * specs of the `chromium` project may call it: `mobile` and `pl-PL` can run
   * while `module-gate` has maker switched off, and this would undo that.
   */
  async enableAllModules(token: string): Promise<void> {
    // stats, printing and announcements are always on: a toggle for them is
    // refused, so they are not asked for.
    const modulesToEnable = [
      "recipes",
      "shopping_lists",
      "stock_takes",
      "webhooks",
      "api_keys",
      "approvals",
      "warehouse",
      "equipment",
      "purchase_orders",
      "partners",
      "maker",
    ];
    for (const mod of modulesToEnable) {
      await this.toggleModule(token, mod, true);
    }
  }

  /** Every row of a paged list; an E2E database holds more than one page. */
  private async everyPage(
    token: string,
    path: string,
  ): Promise<Array<{ id: string; name: string }>> {
    const rows: Array<{ id: string; name: string }> = [];
    for (;;) {
      const response = await this.request.get(
        `${path}?limit=200&offset=${rows.length}`,
        { headers: { Authorization: `Bearer ${token}` } },
      );
      if (!response.ok()) return rows;
      const page = await response.json();
      rows.push(...page.items);
      if (!page.has_more || page.items.length === 0) return rows;
    }
  }

  async listStorages(
    token: string,
  ): Promise<Array<{ id: string; name: string }>> {
    return this.everyPage(token, "/api/v1/locations");
  }

  async listCategories(
    token: string,
  ): Promise<Array<{ id: string; name: string }>> {
    return this.everyPage(token, "/api/v1/categories");
  }

  async listItems(
    token: string,
    params?: string,
  ): Promise<Array<{ id: string; name: string }>> {
    const url = params ? `/api/v1/items?${params}` : "/api/v1/items";
    const response = await this.request.get(url, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok()) return [];
    const data = await response.json();
    return Array.isArray(data) ? data : (data.items ?? []);
  }

  async createInvite(token: string): Promise<{ invite_code: string }> {
    const response = await this.request.post(
      "/api/v1/organizations/my/invitation-code",
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to create invite: ${await response.text()}`);
    const data = await response.json();
    // Backend returns { code, expires_at } — map to { invite_code }
    return { invite_code: data.code };
  }

  /**
   * Apply a partial patch to the organization's settings.
   *
   * `PUT /organizations` REPLACES the settings object — it only carries the
   * existing encrypted secrets over — so the patch has to be merged on the
   * client, exactly as the settings UI does. Sending the patch alone would
   * wipe every other key.
   */
  async updateOrganizationSettings(
    token: string,
    patch: Record<string, unknown>,
  ): Promise<void> {
    const headers = { Authorization: `Bearer ${token}` };
    const current = await this.request.get("/api/v1/organizations/my", {
      headers,
    });
    if (!current.ok())
      throw new Error(`Failed to read organization: ${await current.text()}`);
    const org = (await current.json()) as {
      settings?: Record<string, unknown> | null;
    };

    const response = await this.request.put("/api/v1/organizations", {
      headers,
      data: { settings: { ...(org.settings ?? {}), ...patch } },
    });
    if (!response.ok())
      throw new Error(
        `Failed to update organization settings: ${await response.text()}`,
      );
  }

  async setUserLanguage(token: string, language: string): Promise<void> {
    await this.request.post("/api/v1/auth/me/language", {
      headers: { Authorization: `Bearer ${token}` },
      data: { language },
    });
  }

  async listStockTakes(
    token: string,
  ): Promise<Array<{ id: string; status: string; name: string }>> {
    const response = await this.request.get("/api/v1/stock-takes", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok()) return [];
    const data = await response.json();
    return data.items ?? [];
  }

  async createStockTake(
    token: string,
    data: Record<string, unknown>,
  ): Promise<{ id: string }> {
    const response = await this.request.post("/api/v1/stock-takes", {
      headers: { Authorization: `Bearer ${token}` },
      data,
    });
    if (!response.ok())
      throw new Error(`Failed to create stock take: ${await response.text()}`);
    return await response.json();
  }

  async updateStockTakeStatus(
    token: string,
    id: string,
    status: string,
  ): Promise<void> {
    await this.request.patch(`/api/v1/stock-takes/${id}/status`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { status },
    });
  }

  async deleteStockTake(token: string, id: string): Promise<void> {
    const response = await this.request.delete(`/api/v1/stock-takes/${id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok() && response.status() !== 404)
      throw new Error(`Failed to delete stock take: ${await response.text()}`);
  }

  async createWorkflow(
    token: string,
    data: Record<string, unknown>,
  ): Promise<{ id: string }> {
    const headers = { Authorization: `Bearer ${token}` };
    // A workflow has to say whose submissions it holds; the specs that do
    // not care hold everyone's, which is what every workflow did before.
    // One that comes into force must also name the scope it will hold, and
    // that is readable only from the list: save it off, read, switch on.
    const response = await this.request.post("/api/v1/approvals/workflows", {
      headers,
      data: {
        requester_scope: { everyone: true },
        ...data,
        is_active: false,
      },
    });
    if (!response.ok())
      throw new Error(`Failed to create workflow: ${await response.text()}`);
    const created: { id: string } = await response.json();
    if (data.is_active !== true) return created;
    const listed = await this.request.get("/api/v1/approvals/workflows", {
      headers,
    });
    const row = (await listed.json()).items.find(
      (w: { id: string }) => w.id === created.id,
    );
    const switched = await this.request.patch(
      `/api/v1/approvals/workflows/${created.id}`,
      {
        headers,
        data: { is_active: true, expected_scope: row?.scope ?? null },
      },
    );
    if (!switched.ok())
      throw new Error(`Failed to switch workflow on: ${await switched.text()}`);
    return created;
  }

  async deleteWorkflow(token: string, id: string): Promise<void> {
    const response = await this.request.delete(
      `/api/v1/approvals/workflows/${id}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok() && response.status() !== 404)
      throw new Error(`Failed to delete workflow: ${await response.text()}`);
  }

  async listWorkflows(
    token: string,
  ): Promise<Array<{ id: string; name: string; target_type: string }>> {
    const response = await this.request.get("/api/v1/approvals/workflows", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok()) return [];
    return (await response.json()).items;
  }

  async createDocument(
    token: string,
    data: Record<string, unknown>,
    retries = 2,
  ): Promise<{ id: string; number: string }> {
    for (let attempt = 0; attempt <= retries; attempt++) {
      const response = await this.request.post("/api/v1/warehouse/documents", {
        headers: { Authorization: `Bearer ${token}` },
        data,
      });
      if (response.ok()) return await response.json();
      const body = await response.text();
      if (attempt < retries && response.status() === 500) {
        await new Promise((r) => setTimeout(r, 300 * (attempt + 1)));
        continue;
      }
      throw new Error(`Failed to create document: ${body}`);
    }
    throw new Error("Failed to create document after retries");
  }

  /**
   * An INT (transfer) document whose lines name the stock they take from.
   * Confirm refuses lines that name only a product — the executors move
   * stock by record — so each line first seeds a stocked item at the source
   * location and then references it by ``item_id``.
   */
  async createIntDocumentWithStock(
    token: string,
    data: {
      source_location_id: string;
      target_location_id: string;
      lines: Array<{ name: string; expected_quantity: number }>;
      notes?: string;
      scheduled_date?: string;
    },
  ): Promise<{ id: string; number: string }> {
    const lines: Array<{ item_id: string; expected_quantity: number }> = [];
    for (const line of data.lines) {
      const itemResp = await this.request.post("/api/v1/items", {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          name: line.name,
          quantity: line.expected_quantity,
          location_id: data.source_location_id,
        },
      });
      if (!itemResp.ok())
        throw new Error(
          `Failed to seed stock item for INT line: ${await itemResp.text()}`,
        );
      const item = await itemResp.json();
      lines.push({
        item_id: item.id,
        expected_quantity: line.expected_quantity,
      });
    }
    return await this.createDocument(token, {
      type: "INT",
      source_location_id: data.source_location_id,
      target_location_id: data.target_location_id,
      notes: data.notes,
      scheduled_date: data.scheduled_date,
      lines,
    });
  }

  async deleteDocument(token: string, id: string): Promise<void> {
    const response = await this.request.delete(
      `/api/v1/warehouse/documents/${id}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok() && response.status() !== 404)
      throw new Error(`Failed to delete document: ${await response.text()}`);
  }

  async confirmDocument(token: string, id: string): Promise<unknown> {
    const response = await this.request.patch(
      `/api/v1/warehouse/documents/${id}/confirm`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to confirm document: ${await response.text()}`);
    return await response.json();
  }

  async completeDocument(token: string, id: string): Promise<unknown> {
    const response = await this.request.patch(
      `/api/v1/warehouse/documents/${id}/complete`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: { complete_as_planned: true },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to complete document: ${await response.text()}`);
    return await response.json();
  }

  async cancelDocument(token: string, id: string): Promise<void> {
    const response = await this.request.patch(
      `/api/v1/warehouse/documents/${id}/cancel`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok() && response.status() !== 404)
      throw new Error(`Failed to cancel document: ${await response.text()}`);
  }

  async listDocuments(
    token: string,
    params?: string,
  ): Promise<
    Array<{ id: string; number: string; type: string; status: string }>
  > {
    const url = params
      ? `/api/v1/warehouse/documents?${params}`
      : "/api/v1/warehouse/documents";
    const response = await this.request.get(url, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok()) return [];
    const data = await response.json();
    return Array.isArray(data) ? data : (data.items ?? []);
  }

  async getDocument(
    token: string,
    id: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.get(
      `/api/v1/warehouse/documents/${id}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to get document: ${await response.text()}`);
    return await response.json();
  }

  async getDocumentApproval(
    token: string,
    docId: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.get(
      `/api/v1/approvals/documents/${docId}/approval`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok()) return {};
    return await response.json();
  }

  async requestDocumentApproval(
    token: string,
    docId: string,
  ): Promise<unknown> {
    const response = await this.request.post(
      `/api/v1/approvals/documents/${docId}/request-approval`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to request approval: ${await response.text()}`);
    return await response.json();
  }

  async approveDocument(token: string, docId: string): Promise<unknown> {
    const response = await this.request.post(
      `/api/v1/approvals/documents/${docId}/approve`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to approve document: ${await response.text()}`);
    return await response.json();
  }

  async createEquipmentItem(
    token: string,
    data: Record<string, unknown>,
  ): Promise<{ id: string }> {
    const response = await this.request.post("/api/v1/items", {
      headers: { Authorization: `Bearer ${token}` },
      data,
    });
    if (!response.ok())
      throw new Error(
        `Failed to create equipment item: ${await response.text()}`,
      );
    return await response.json();
  }

  async getEquipmentDashboard(token: string): Promise<Record<string, unknown>> {
    const response = await this.request.get("/api/v1/equipment/dashboard", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok()) return {};
    return await response.json();
  }

  async getAssetValuation(
    token: string,
    itemId: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.get(
      `/api/v1/equipment/${itemId}/valuation`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok()) return {};
    return await response.json();
  }

  async getFleetValuation(token: string): Promise<Record<string, unknown>> {
    const response = await this.request.get("/api/v1/equipment/valuation", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok()) return {};
    return await response.json();
  }

  async listPartners(
    token: string,
    params?: string,
  ): Promise<Array<{ id: string; name: string; is_active: boolean }>> {
    const url = params ? `/api/v1/partners?${params}` : "/api/v1/partners";
    const response = await this.request.get(url, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok()) return [];
    const data = await response.json();
    return data.items ?? data;
  }

  async createPartner(
    token: string,
    data: Record<string, unknown>,
  ): Promise<{ id: string }> {
    const response = await this.request.post("/api/v1/partners", {
      headers: { Authorization: `Bearer ${token}` },
      data,
    });
    if (!response.ok())
      throw new Error(`Failed to create partner: ${await response.text()}`);
    return await response.json();
  }

  async deletePartner(token: string, id: string): Promise<void> {
    const response = await this.request.delete(`/api/v1/partners/${id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok() && response.status() !== 404)
      throw new Error(`Failed to delete partner: ${await response.text()}`);
  }

  async createPurchaseOrder(
    token: string,
    data: Record<string, unknown>,
  ): Promise<{ id: string; number: string }> {
    const response = await this.request.post("/api/v1/purchase-orders", {
      headers: { Authorization: `Bearer ${token}` },
      data,
    });
    if (!response.ok())
      throw new Error(
        `Failed to create purchase order: ${await response.text()}`,
      );
    return await response.json();
  }

  async deletePurchaseOrder(token: string, id: string): Promise<void> {
    const response = await this.request.delete(
      `/api/v1/purchase-orders/${id}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok() && response.status() !== 404)
      throw new Error(
        `Failed to delete purchase order: ${await response.text()}`,
      );
  }

  /** A draft order becomes the confirmed order the receiving screen waits for. */
  async confirmPurchaseOrder(
    token: string,
    id: string,
  ): Promise<{ id: string; status: string }> {
    const response = await this.request.post(
      `/api/v1/purchase-orders/${id}/confirm`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    if (!response.ok())
      throw new Error(
        `Failed to confirm purchase order: ${await response.text()}`,
      );
    return await response.json();
  }

  async listApiKeys(
    token: string,
  ): Promise<Array<{ id: string; name: string }>> {
    const response = await this.request.get("/api/v1/api-keys", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok()) return [];
    return (await response.json()).items;
  }

  async createApiKey(
    token: string,
    data: Record<string, unknown>,
  ): Promise<{ id: string }> {
    const response = await this.request.post("/api/v1/api-keys", {
      headers: { Authorization: `Bearer ${token}` },
      data,
    });
    if (!response.ok())
      throw new Error(`Failed to create API key: ${await response.text()}`);
    return await response.json();
  }

  async deleteApiKey(token: string, id: string): Promise<void> {
    const response = await this.request.delete(`/api/v1/api-keys/${id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok() && response.status() !== 404)
      throw new Error(`Failed to delete API key: ${await response.text()}`);
  }

  // ── Documents — extended ──────────────────────────────────────────────

  async updateDocument(
    token: string,
    id: string,
    data: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.put(
      `/api/v1/warehouse/documents/${id}`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        data,
      },
    );
    if (!response.ok())
      throw new Error(`Failed to update document: ${await response.text()}`);
    return await response.json();
  }

  async getDocumentRegister(
    token: string,
    params?: string,
  ): Promise<Record<string, unknown>> {
    const defaults = "date_from=2024-01-01&date_to=2026-12-31";
    const qs = params || defaults;
    // ``/register`` is the CSV export; the JSON summary lives at
    // ``/register/summary`` (rows: ``/register/rows``).
    const url = `/api/v1/warehouse/register/summary?${qs}`;
    const response = await this.request.get(url, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok())
      throw new Error(
        `Failed to get document register: ${await response.text()}`,
      );
    return await response.json();
  }

  async createCorrection(
    token: string,
    data: Record<string, unknown>,
  ): Promise<{ id: string; number: string }> {
    const response = await this.request.post("/api/v1/warehouse/corrections", {
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      data,
    });
    if (!response.ok())
      throw new Error(`Failed to create correction: ${await response.text()}`);
    return await response.json();
  }

  async listCorrections(
    token: string,
    docId: string,
  ): Promise<Array<{ id: string } & Record<string, unknown>>> {
    const response = await this.request.get(
      `/api/v1/warehouse/documents/${docId}/corrections`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok()) return [];
    return (await response.json()).items;
  }

  async createReturn(
    token: string,
    docId: string,
    data: Record<string, unknown>,
  ): Promise<{ id: string; number: string }> {
    const response = await this.request.post(
      `/api/v1/warehouse/documents/${docId}/return`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        data,
      },
    );
    if (!response.ok())
      throw new Error(`Failed to create return: ${await response.text()}`);
    return await response.json();
  }

  // ── Equipment — assignments (checkout/checkin) ────────────────────────

  async checkoutAsset(
    token: string,
    data: Record<string, unknown>,
  ): Promise<{ id: string }> {
    const response = await this.request.post("/api/v1/equipment/assignments", {
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      data,
    });
    if (!response.ok())
      throw new Error(`Failed to checkout asset: ${await response.text()}`);
    return await response.json();
  }

  async checkinAsset(
    token: string,
    assignmentId: string,
    data?: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.post(
      `/api/v1/equipment/assignments/${assignmentId}/checkin`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        data: data ?? {},
      },
    );
    if (!response.ok())
      throw new Error(`Failed to checkin asset: ${await response.text()}`);
    return await response.json();
  }

  async listAssignments(
    token: string,
    params?: string,
  ): Promise<Array<Record<string, unknown>>> {
    const url = params
      ? `/api/v1/equipment/assignments?${params}`
      : "/api/v1/equipment/assignments";
    const response = await this.request.get(url, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok()) return [];
    const data = await response.json();
    return data.items ?? data;
  }

  // ── Equipment — maintenance ───────────────────────────────────────────

  async addMaintenanceLog(
    token: string,
    data: Record<string, unknown>,
  ): Promise<{ id: string }> {
    const response = await this.request.post("/api/v1/equipment/maintenance", {
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      data,
    });
    if (!response.ok())
      throw new Error(
        `Failed to add maintenance log: ${await response.text()}`,
      );
    return await response.json();
  }

  async editMaintenanceLog(
    token: string,
    logId: string,
    data: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.put(
      `/api/v1/equipment/maintenance/${logId}`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        data,
      },
    );
    if (!response.ok())
      throw new Error(
        `Failed to edit maintenance log: ${await response.text()}`,
      );
    return await response.json();
  }

  async removeMaintenanceLog(token: string, logId: string): Promise<void> {
    const response = await this.request.delete(
      `/api/v1/equipment/maintenance/${logId}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok() && response.status() !== 404)
      throw new Error(
        `Failed to remove maintenance log: ${await response.text()}`,
      );
  }

  async listMaintenanceLogs(
    token: string,
    itemId: string,
  ): Promise<Array<Record<string, unknown>>> {
    const response = await this.request.get(
      `/api/v1/equipment/maintenance/item/${itemId}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok()) return [];
    return (await response.json()).items;
  }

  // ── Equipment — models ────────────────────────────────────────────────

  async createModel(
    token: string,
    data: Record<string, unknown>,
  ): Promise<{ id: string }> {
    const response = await this.request.post("/api/v1/equipment/models", {
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      data,
    });
    if (!response.ok())
      throw new Error(`Failed to create model: ${await response.text()}`);
    return await response.json();
  }

  async listModels(
    token: string,
  ): Promise<Array<{ id: string; name: string }>> {
    const response = await this.request.get("/api/v1/equipment/models", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok()) return [];
    return (await response.json()).items;
  }

  async updateModel(
    token: string,
    modelId: string,
    data: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.put(
      `/api/v1/equipment/models/${modelId}`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        data,
      },
    );
    if (!response.ok())
      throw new Error(`Failed to update model: ${await response.text()}`);
    return await response.json();
  }

  async deleteModel(token: string, modelId: string): Promise<void> {
    const response = await this.request.delete(
      `/api/v1/equipment/models/${modelId}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok() && response.status() !== 404)
      throw new Error(`Failed to delete model: ${await response.text()}`);
  }

  async deleteCampaign(token: string, campaignId: string): Promise<void> {
    const response = await this.request.delete(
      `/api/v1/equipment/campaigns/${campaignId}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok() && response.status() !== 404)
      throw new Error(`Failed to delete campaign: ${await response.text()}`);
  }

  // ── Rules, prices and templates that fill the lists of a phone ────────

  /** POST a JSON body to `url` and return the created record. */
  async postJson<T = { id: string }>(
    token: string,
    url: string,
    data?: Record<string, unknown>,
  ): Promise<T> {
    const response = await this.request.post(url, {
      headers: { Authorization: `Bearer ${token}` },
      data,
    });
    if (!response.ok())
      throw new Error(`POST ${url} failed: ${await response.text()}`);
    return await response.json();
  }

  /** DELETE `url`; a record that is already gone is not an error. */
  async deletePath(token: string, url: string): Promise<void> {
    const response = await this.request.delete(url, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok() && response.status() !== 404)
      throw new Error(`DELETE ${url} failed: ${await response.text()}`);
  }

  async cloneModel(token: string, modelId: string): Promise<{ id: string }> {
    const response = await this.request.post(
      `/api/v1/equipment/models/${modelId}/clone`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to clone model: ${await response.text()}`);
    return await response.json();
  }

  // ── Equipment — campaigns ─────────────────────────────────────────────

  async createCampaign(
    token: string,
    data: Record<string, unknown>,
  ): Promise<{ id: string }> {
    const response = await this.request.post("/api/v1/equipment/campaigns", {
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      data,
    });
    if (!response.ok())
      throw new Error(`Failed to create campaign: ${await response.text()}`);
    return await response.json();
  }

  async listCampaigns(
    token: string,
  ): Promise<Array<{ id: string; name: string; status: string }>> {
    const response = await this.request.get("/api/v1/equipment/campaigns", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok()) return [];
    return (await response.json()).items;
  }

  async launchCampaign(
    token: string,
    campaignId: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.post(
      `/api/v1/equipment/campaigns/${campaignId}/launch`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to launch campaign: ${await response.text()}`);
    return await response.json();
  }

  // ── Equipment — retire ────────────────────────────────────────────────

  async retireEquipment(token: string, itemId: string): Promise<void> {
    const response = await this.request.post(
      `/api/v1/equipment/items/${itemId}/retire`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to retire equipment: ${await response.text()}`);
  }

  async archiveEquipment(token: string, itemId: string): Promise<void> {
    const response = await this.request.post(
      `/api/v1/equipment/items/${itemId}/archive`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to archive equipment: ${await response.text()}`);
  }

  // ── Approvals — extended ──────────────────────────────────────────────

  async rejectRequest(
    token: string,
    requestId: string,
    data?: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.post(
      `/api/v1/approvals/requests/${requestId}/reject`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        data: data ?? {},
      },
    );
    if (!response.ok())
      throw new Error(`Failed to reject request: ${await response.text()}`);
    return await response.json();
  }

  async getRequest(
    token: string,
    requestId: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.get(
      `/api/v1/approvals/requests/${requestId}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to get request: ${await response.text()}`);
    return await response.json();
  }

  async listRequests(
    token: string,
    params?: string,
  ): Promise<Array<Record<string, unknown>>> {
    const url = params
      ? `/api/v1/approvals/requests?${params}`
      : "/api/v1/approvals/requests";
    const response = await this.request.get(url, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok()) return [];
    const data = await response.json();
    // Endpoint is paginated ({items, total, ...}); older callers expect an array.
    return Array.isArray(data) ? data : (data.items ?? []);
  }

  async approveRequest(
    token: string,
    requestId: string,
    data?: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.post(
      `/api/v1/approvals/requests/${requestId}/approve`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        data: data ?? {},
      },
    );
    if (!response.ok())
      throw new Error(`Failed to approve request: ${await response.text()}`);
    return await response.json();
  }

  async updateWorkflow(
    token: string,
    workflowId: string,
    data: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.patch(
      `/api/v1/approvals/workflows/${workflowId}`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        data,
      },
    );
    if (!response.ok())
      throw new Error(`Failed to update workflow: ${await response.text()}`);
    return await response.json();
  }

  async getWorkflow(
    token: string,
    workflowId: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.get(
      `/api/v1/approvals/workflows/${workflowId}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to get workflow: ${await response.text()}`);
    return await response.json();
  }

  async cleanupApprovals(token: string): Promise<void> {
    const workflows = await this.listWorkflows(token);
    for (const w of workflows) {
      await this.deleteWorkflow(token, w.id as string).catch(() => {});
    }
  }

  // ── Recipes — picking ────────────────────────────────────────────────

  async startPicking(
    token: string,
    recipeId: string,
    servings = 1,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.post(
      `/api/v1/recipes/${recipeId}/picking/start`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        data: { servings },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to start picking: ${await response.text()}`);
    return await response.json();
  }

  async scanPicking(
    token: string,
    recipeId: string,
    sessionId: string,
    data: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.post(
      `/api/v1/recipes/${recipeId}/picking/${sessionId}/scan`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        data,
      },
    );
    if (!response.ok())
      throw new Error(`Failed to scan picking: ${await response.text()}`);
    return await response.json();
  }

  async completePicking(
    token: string,
    recipeId: string,
    sessionId: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.post(
      `/api/v1/recipes/${recipeId}/picking/${sessionId}/complete`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to complete picking: ${await response.text()}`);
    return await response.json();
  }

  async cancelPicking(
    token: string,
    recipeId: string,
    sessionId: string,
  ): Promise<void> {
    const response = await this.request.delete(
      `/api/v1/recipes/${recipeId}/picking/${sessionId}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok() && response.status() !== 404)
      throw new Error(`Failed to cancel picking: ${await response.text()}`);
  }

  async undoPick(
    token: string,
    recipeId: string,
    sessionId: string,
    ingredientId: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.post(
      `/api/v1/recipes/${recipeId}/picking/${sessionId}/undo`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        data: { ingredient_id: ingredientId },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to undo pick: ${await response.text()}`);
    return await response.json();
  }

  async getRecipeHistory(
    token: string,
    recipeId: string,
  ): Promise<Array<Record<string, unknown>>> {
    const response = await this.request.get(
      `/api/v1/recipes/${recipeId}/history`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok()) return [];
    return (await response.json()).items;
  }

  // ── Recipes — availability ───────────────────────────────────────────

  async getRecipeAvailability(
    token: string,
    recipeId: string,
    servings = 0,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.get(
      `/api/v1/recipes/${recipeId}/availability?servings=${servings}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(
        `Failed to get recipe availability: ${await response.text()}`,
      );
    return await response.json();
  }

  async getAvailableRecipes(
    token: string,
    params?: string,
  ): Promise<Array<Record<string, unknown>>> {
    const url = params
      ? `/api/v1/recipes/available?${params}`
      : "/api/v1/recipes/available";
    const response = await this.request.get(url, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok()) return [];
    return (await response.json()).items;
  }

  // ── Recipes — tags ───────────────────────────────────────────────────

  async listTags(
    token: string,
  ): Promise<Array<{ name: string; count: number; color: string | null }>> {
    const response = await this.request.get("/api/v1/recipes/tags", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok()) return [];
    return (await response.json()).items;
  }

  async mergeTags(
    token: string,
    oldTag: string,
    newTag: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.post("/api/v1/recipes/tags/merge", {
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      data: { old_tag: oldTag, new_tag: newTag },
    });
    if (!response.ok())
      throw new Error(`Failed to merge tags: ${await response.text()}`);
    return await response.json();
  }

  async setTagColor(
    token: string,
    tagName: string,
    color: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.patch(
      `/api/v1/recipes/tags/${tagName}/color`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        data: { color },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to set tag color: ${await response.text()}`);
    return await response.json();
  }

  // ── Recipes — unit conversions ───────────────────────────────────────

  async listUnitConversions(
    token: string,
  ): Promise<Array<Record<string, unknown>>> {
    const response = await this.request.get(
      "/api/v1/recipes/unit-conversions",
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok()) return [];
    return (await response.json()).items;
  }

  async createUnitConversion(
    token: string,
    data: Record<string, unknown>,
  ): Promise<{ id: string }> {
    const response = await this.request.post(
      "/api/v1/recipes/unit-conversions",
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        data,
      },
    );
    if (!response.ok())
      throw new Error(
        `Failed to create unit conversion: ${await response.text()}`,
      );
    return await response.json();
  }

  async deleteUnitConversion(token: string, id: string): Promise<void> {
    const response = await this.request.delete(
      `/api/v1/recipes/unit-conversions/${id}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok() && response.status() !== 404)
      throw new Error(
        `Failed to delete unit conversion: ${await response.text()}`,
      );
  }

  // ── Recipes — meal plans ─────────────────────────────────────────────

  async createMealPlan(
    token: string,
    data: Record<string, unknown>,
  ): Promise<{ id: string }> {
    const response = await this.request.post("/api/v1/recipes/meal-plans", {
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      data,
    });
    if (!response.ok())
      throw new Error(`Failed to create meal plan: ${await response.text()}`);
    return await response.json();
  }

  async listMealPlans(
    token: string,
  ): Promise<Array<{ id: string; name: string | null; entry_count: number }>> {
    const response = await this.request.get(
      "/api/v1/recipes/meal-plans?limit=100",
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok()) return [];
    return (await response.json()).items;
  }

  async deleteMealPlan(token: string, planId: string): Promise<void> {
    const response = await this.request.delete(
      `/api/v1/recipes/meal-plans/${planId}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok() && response.status() !== 404)
      throw new Error(`Failed to delete meal plan: ${await response.text()}`);
  }

  async addMealPlanEntry(
    token: string,
    planId: string,
    data: Record<string, unknown>,
  ): Promise<{ id: string }> {
    const response = await this.request.post(
      `/api/v1/recipes/meal-plans/${planId}/entries`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        data,
      },
    );
    if (!response.ok())
      throw new Error(
        `Failed to add meal plan entry: ${await response.text()}`,
      );
    return await response.json();
  }

  async deleteMealPlanEntry(
    token: string,
    planId: string,
    entryId: string,
  ): Promise<void> {
    const response = await this.request.delete(
      `/api/v1/recipes/meal-plans/${planId}/entries/${entryId}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok() && response.status() !== 404)
      throw new Error(
        `Failed to delete meal plan entry: ${await response.text()}`,
      );
  }

  async generateMealPlanShoppingList(
    token: string,
    planId: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.post(
      `/api/v1/recipes/meal-plans/${planId}/generate-shopping-list`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(
        `Failed to generate shopping list: ${await response.text()}`,
      );
    return await response.json();
  }

  async getMealPlanSuggestions(
    token: string,
    date: string,
    slot: string,
    count = 5,
  ): Promise<Array<Record<string, unknown>>> {
    const response = await this.request.get(
      `/api/v1/recipes/meal-plans/suggestions?date=${date}&slot=${slot}&count=${count}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok()) return [];
    return await response.json();
  }

  // ── Stock Takes — extended ───────────────────────────────────────────

  async getStockTake(
    token: string,
    id: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.get(`/api/v1/stock-takes/${id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok())
      throw new Error(`Failed to get stock take: ${await response.text()}`);
    return await response.json();
  }

  async getStockTakeItems(
    token: string,
    stockTakeId: string,
  ): Promise<Array<Record<string, unknown>>> {
    const response = await this.request.get(
      `/api/v1/stock-takes/${stockTakeId}/items`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok()) return [];
    const data = await response.json();
    return Array.isArray(data) ? data : (data.items ?? []);
  }

  async countStockTakeItem(
    token: string,
    stockTakeId: string,
    itemId: string,
    countedQuantity: number,
    notes?: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.patch(
      `/api/v1/stock-takes/${stockTakeId}/items/${itemId}/count`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        data: {
          counted_quantity: countedQuantity,
          ...(notes ? { notes } : {}),
        },
      },
    );
    if (!response.ok())
      throw new Error(
        `Failed to count stock take item: ${await response.text()}`,
      );
    return await response.json();
  }

  async bulkCountStockTakeItems(
    token: string,
    stockTakeId: string,
    items: Array<{ item_id: string; counted_quantity: number; notes?: string }>,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.patch(
      `/api/v1/stock-takes/${stockTakeId}/items/bulk-count`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        data: { items },
      },
    );
    if (!response.ok())
      throw new Error(
        `Failed to bulk count stock take items: ${await response.text()}`,
      );
    return await response.json();
  }

  async completeStockTake(
    token: string,
    stockTakeId: string,
    applyAdjustments = true,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.post(
      `/api/v1/stock-takes/${stockTakeId}/complete`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        data: { apply_adjustments: applyAdjustments },
      },
    );
    if (!response.ok())
      throw new Error(
        `Failed to complete stock take: ${await response.text()}`,
      );
    return await response.json();
  }

  async getStockTakeReport(
    token: string,
    stockTakeId: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.get(
      `/api/v1/stock-takes/${stockTakeId}/report`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(
        `Failed to get stock take report: ${await response.text()}`,
      );
    return await response.json();
  }

  // ── Items — extended ─────────────────────────────────────────────────

  async getItem(
    token: string,
    itemId: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.get(`/api/v1/items/${itemId}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok())
      throw new Error(`Failed to get item: ${await response.text()}`);
    return await response.json();
  }

  async moveItem(
    token: string,
    itemId: string,
    targetLocationId: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.patch(`/api/v1/items/${itemId}/move`, {
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      data: { to_location_id: targetLocationId },
    });
    if (!response.ok())
      throw new Error(`Failed to move item: ${await response.text()}`);
    return await response.json();
  }

  async adjustQuantity(
    token: string,
    itemId: string,
    newQuantity: number,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.patch(
      `/api/v1/items/${itemId}/quantity`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        data: { quantity: newQuantity },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to adjust quantity: ${await response.text()}`);
    return await response.json();
  }

  async restoreItem(
    token: string,
    itemId: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.post(
      `/api/v1/items/${itemId}/restore`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to restore item: ${await response.text()}`);
    return await response.json();
  }

  async purgeItem(
    token: string,
    itemId: string,
    reason = "E2E test cleanup",
  ): Promise<void> {
    const response = await this.request.delete(
      `/api/v1/items/${itemId}/purge?reason=${encodeURIComponent(reason)}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok() && response.status() !== 404)
      throw new Error(`Failed to purge item: ${await response.text()}`);
  }

  async getArchivedItems(
    token: string,
  ): Promise<Array<Record<string, unknown>>> {
    const response = await this.request.get("/api/v1/items/archived", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok()) return [];
    const data = await response.json();
    return Array.isArray(data) ? data : (data.items ?? []);
  }

  // ── Shopping Lists — extended ───────────────────────────────────────────

  async updateShoppingList(
    token: string,
    listId: string,
    data: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.put(
      `/api/v1/shopping-lists/${listId}`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data,
      },
    );
    if (!response.ok())
      throw new Error(
        `Failed to update shopping list: ${await response.text()}`,
      );
    return await response.json();
  }

  async updateShoppingListItem(
    token: string,
    listId: string,
    itemId: string,
    data: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.put(
      `/api/v1/shopping-lists/${listId}/items/${itemId}`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data,
      },
    );
    if (!response.ok())
      throw new Error(
        `Failed to update shopping list item: ${await response.text()}`,
      );
    return await response.json();
  }

  async unpurchaseShoppingListItem(
    token: string,
    listId: string,
    itemId: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.patch(
      `/api/v1/shopping-lists/${listId}/items/${itemId}/unpurchase`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to unpurchase item: ${await response.text()}`);
    return await response.json();
  }

  async bulkAddShoppingListItems(
    token: string,
    listId: string,
    items: Array<Record<string, unknown>>,
  ): Promise<Array<Record<string, unknown>>> {
    const response = await this.request.post(
      `/api/v1/shopping-lists/${listId}/items/bulk`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: items,
      },
    );
    if (!response.ok())
      throw new Error(`Failed to bulk add items: ${await response.text()}`);
    return await response.json();
  }

  // ── Partners — extended ─────────────────────────────────────────────────

  async getPartner(
    token: string,
    partnerId: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.get(`/api/v1/partners/${partnerId}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok())
      throw new Error(`Failed to get partner: ${await response.text()}`);
    return await response.json();
  }

  async updatePartner(
    token: string,
    partnerId: string,
    data: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.put(`/api/v1/partners/${partnerId}`, {
      headers: { Authorization: `Bearer ${token}` },
      data,
    });
    if (!response.ok())
      throw new Error(`Failed to update partner: ${await response.text()}`);
    return await response.json();
  }

  async activatePartner(
    token: string,
    partnerId: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.patch(
      `/api/v1/partners/${partnerId}/activate`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to activate partner: ${await response.text()}`);
    return await response.json();
  }

  // ── Storage Locations — extended ────────────────────────────────────────

  async getStorageTree(token: string): Promise<Array<Record<string, unknown>>> {
    const response = await this.request.get("/api/v1/locations/tree", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok()) return [];
    return await response.json();
  }

  async getStorageSummary(
    token: string,
    storageId: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.get(
      `/api/v1/locations/${storageId}/summary`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(
        `Failed to get storage summary: ${await response.text()}`,
      );
    return await response.json();
  }

  async getStorageBreadcrumb(
    token: string,
    storageId: string,
  ): Promise<Array<Record<string, unknown>>> {
    const response = await this.request.get(
      `/api/v1/locations/${storageId}/breadcrumb`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok()) return [];
    return await response.json();
  }

  // ── Labels — extended ───────────────────────────────────────────────────

  async assignLabelToItem(
    token: string,
    shortCode: string,
    itemId: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.post(
      `/api/v1/labels/pool/${shortCode}/assign-item?item_id=${itemId}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to assign label: ${await response.text()}`);
    return await response.json();
  }

  async unassignLabel(
    token: string,
    shortCode: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.post(
      `/api/v1/labels/pool/${shortCode}/unassign`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to unassign label: ${await response.text()}`);
    return await response.json();
  }

  async getLabelPoolStats(token: string): Promise<Record<string, unknown>> {
    const response = await this.request.get("/api/v1/labels/pool/stats", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok())
      throw new Error(
        `Failed to get label pool stats: ${await response.text()}`,
      );
    return await response.json();
  }

  // ── Scan ────────────────────────────────────────────────────────────────

  async scanCode(
    token: string,
    code: string,
  ): Promise<Record<string, unknown>> {
    const response = await this.request.get(
      `/api/v1/labels/scan/${encodeURIComponent(code)}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to scan code: ${await response.text()}`);
    return await response.json();
  }

  // ── Maker module ───────────────────────────────────────────────────────

  /**
   * Create a ProductTemplate. Used by maker e2e tests to seed parent/child
   * templates for BoM lines and production orders.
   */
  async createProductTemplate(
    token: string,
    data: { name: string; sku?: string; barcode?: string },
  ): Promise<{ id: string }> {
    const response = await this.request.post(
      "/api/v1/items/product-templates",
      {
        headers: { Authorization: `Bearer ${token}` },
        data,
      },
    );
    if (!response.ok())
      throw new Error(
        `Failed to create product template: ${await response.text()}`,
      );
    return await response.json();
  }

  /**
   * Create an Item whose template is the given ProductTemplate id and seed
   * stock at the given location for the requested qty. The request names the
   * card by id, so no name matching runs and a second card of the same name
   * (another spec's, a shared one) cannot take the record; the answer is
   * checked to prove it.
   *
   * This is the canonical way to seed enough stock for the maker
   * completion pipeline (which consumes via ``consume_across_locations``).
   */
  async createItemForTemplate(
    token: string,
    data: {
      name: string;
      template_id: string;
      location_id: string;
      quantity: number;
    },
  ): Promise<{ id: string; template_id: string }> {
    const response = await this.request.post("/api/v1/items", {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        name: data.name,
        template_id: data.template_id,
        quantity: data.quantity,
        location_id: data.location_id,
      },
    });
    if (!response.ok())
      throw new Error(
        `Failed to create item for template: ${await response.text()}`,
      );
    const item = await response.json();
    if (item.template_id !== data.template_id)
      throw new Error(
        `Item ${item.id} joined template ${item.template_id}, not ${data.template_id}`,
      );
    return { id: item.id, template_id: item.template_id };
  }

  /**
   * Seed stock for a product template by creating a matching item. Idempotent:
   * returns the existing item id when an item with the same name already has
   * stock at the same location.
   */
  async seedStock(
    token: string,
    data: {
      product_template_id: string;
      product_template_name: string;
      location_id: string;
      quantity: number;
    },
  ): Promise<{ item_id: string }> {
    const item = await this.createItemForTemplate(token, {
      name: data.product_template_name,
      template_id: data.product_template_id,
      location_id: data.location_id,
      quantity: data.quantity,
    });
    return { item_id: item.id };
  }

  /**
   * StockQuant rows for a template at a location — the ledger a warehouse
   * document is supposed to move. The core owns the ledger:
   * ``GET /api/v1/stock-quants`` answers with a paginated envelope, and the
   * location filter accepts the storage location id (the query covers the
   * subtree beneath it).
   */
  async listQuants(
    token: string,
    productTemplateId: string,
    storageLocationId: string,
  ): Promise<Array<{ quantity: number; reserved_quantity: number }>> {
    const response = await this.request.get(
      `/api/v1/stock-quants?product_template_id=${productTemplateId}` +
        `&location_id=${storageLocationId}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    if (!response.ok())
      throw new Error(`Failed to list quants: ${await response.text()}`);
    const page = await response.json();
    return page.items ?? [];
  }

  /** Total on-hand quantity for a template at a location (0 when unseen). */
  async quantityOnHand(
    token: string,
    productTemplateId: string,
    storageLocationId: string,
  ): Promise<number> {
    const quants = await this.listQuants(
      token,
      productTemplateId,
      storageLocationId,
    );
    return quants.reduce((sum, q) => sum + Number(q.quantity), 0);
  }

  /**
   * Product search used by the ProductionCreateSheet picker.
   * Mirrors the documents product-search endpoint.
   */
  async searchProducts(
    token: string,
    query: string,
    limit = 10,
  ): Promise<
    Array<{
      product_template_id: string;
      name: string;
      sku: string | null;
      barcode: string | null;
    }>
  > {
    const response = await this.request.get(
      `/api/v1/warehouse/product-search?q=${encodeURIComponent(query)}&limit=${limit}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    if (!response.ok()) return [];
    return await response.json();
  }

  /**
   * The formula a product's BoM lines belong to: its default one, created
   * on the spot when the product has none yet.
   *
   * `POST /maker/bom` used to do this resolution server-side, which is why
   * it was removed — it always wrote to the *default* formula, so a product
   * with two formulas silently got its lines in the wrong one. Setups that
   * only care about "this product has these ingredients" resolve here
   * instead; a test that means a *specific* formula passes `recipe_id` to
   * `createBomLine` and skips this entirely.
   */
  async resolveDefaultRecipeId(
    token: string,
    outputTemplateId: string,
  ): Promise<string> {
    const response = await this.request.get("/api/v1/maker/recipes", {
      headers: { Authorization: `Bearer ${token}` },
      params: { output_template_id: outputTemplateId, limit: 200 },
    });
    if (!response.ok())
      throw new Error(`Failed to list formulas: ${await response.text()}`);
    const body = (await response.json()) as {
      items: Array<{ id: string; is_default: boolean }>;
    };
    const existing =
      body.items.find((item) => item.is_default) ?? body.items[0];
    if (existing) return existing.id;

    // First formula for this product is auto-default (create_recipe).
    const created = await this.createMakerRecipe(token, {
      output_template_id: outputTemplateId,
      name: "Default",
      batch_yield_qty: "1",
    });
    return created.id;
  }

  /**
   * Add an ingredient line. Give it `recipe_id` to address one formula
   * exactly, or `parent_template_id` to go through the product's default.
   */
  async createBomLine(
    token: string,
    data: {
      parent_template_id?: string;
      recipe_id?: string;
      child_template_id: string;
      qty_per_batch: string;
      unit: string;
      yield_loss_pct?: string;
      notes?: string | null;
    },
  ): Promise<{ id: string }> {
    const { parent_template_id, recipe_id, ...line } = data;
    const recipeId =
      recipe_id ??
      (parent_template_id
        ? await this.resolveDefaultRecipeId(token, parent_template_id)
        : undefined);
    if (!recipeId)
      throw new Error("createBomLine needs recipe_id or parent_template_id");

    const response = await this.request.post(
      `/api/v1/maker/recipes/${recipeId}/bom-lines`,
      { headers: { Authorization: `Bearer ${token}` }, data: line },
    );
    if (!response.ok())
      throw new Error(`Failed to create BoM line: ${await response.text()}`);
    return await response.json();
  }

  async deleteBomLine(token: string, lineId: string): Promise<void> {
    const response = await this.request.delete(`/api/v1/maker/bom/${lineId}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok() && response.status() !== 404)
      throw new Error(`Failed to delete BoM line: ${await response.text()}`);
  }

  async listBomLines(
    token: string,
    parentTemplateId: string,
    page: { limit?: number; offset?: number } = {},
  ): Promise<{
    items: Array<{
      id: string;
      parent_template_id: string;
      child_template_id: string;
      qty_per_batch: string;
      unit: string;
      yield_loss_pct: string;
      notes: string | null;
    }>;
    total: number;
    limit: number;
    offset: number;
    has_more: boolean;
  }> {
    const response = await this.request.get(
      `/api/v1/maker/bom/${parentTemplateId}`,
      {
        headers: { Authorization: `Bearer ${token}` },
        params: { limit: page.limit ?? 200, offset: page.offset ?? 0 },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to list BoM lines: ${await response.text()}`);
    return await response.json();
  }

  async getBomTree(token: string, templateId: string): Promise<unknown> {
    const response = await this.request.get(
      `/api/v1/maker/bom/tree/${templateId}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    if (!response.ok())
      throw new Error(`Failed to get BoM tree: ${await response.text()}`);
    return await response.json();
  }

  async moveBomLine(
    token: string,
    lineId: string,
    newParentTemplateId: string,
  ): Promise<unknown> {
    const response = await this.request.post(
      `/api/v1/maker/bom/${lineId}/move`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: { new_parent_template_id: newParentTemplateId },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to move BoM line: ${await response.text()}`);
    return await response.json();
  }

  /**
   * Cleanup helper: remove all BoM lines owned by the org. Iterates over
   * a list of parent template ids so we don't depend on org-wide endpoint.
   */
  async deleteAllBomLinesForTemplate(
    token: string,
    parentTemplateId: string,
  ): Promise<void> {
    // Read every page before deleting: deleting shifts the offsets under it.
    const ids: string[] = [];
    for (;;) {
      const page = await this.listBomLines(token, parentTemplateId, {
        limit: 1000,
        offset: ids.length,
      });
      ids.push(...page.items.map((line) => line.id));
      if (!page.has_more || page.items.length === 0) break;
    }
    for (const id of ids) await this.deleteBomLine(token, id);
  }

  /**
   * Create a maker formula (POST /api/v1/maker/recipes) — the recipe-catalog
   * entity introduced by the new maker IA. Distinct from the legacy culinary
   * ``createRecipe`` (POST /api/v1/recipes).
   */
  async createMakerRecipe(
    token: string,
    data: {
      output_template_id: string;
      name: string;
      batch_yield_qty?: string;
      reference_price?: string;
    },
  ): Promise<{ id: string; name: string }> {
    const response = await this.request.post("/api/v1/maker/recipes", {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        output_template_id: data.output_template_id,
        name: data.name,
        batch_yield_qty: data.batch_yield_qty ?? "1",
        reference_price: data.reference_price,
      },
    });
    if (!response.ok())
      throw new Error(
        `Failed to create maker recipe: ${await response.text()}`,
      );
    return await response.json();
  }

  /**
   * Full maker recipe detail (GET /api/v1/maker/recipes/{id}) — includes
   * ingredient lines with ``qty_per_batch``.
   */
  async getMakerRecipe(
    token: string,
    recipeId: string,
  ): Promise<{
    id: string;
    name: string;
    output_template_id: string;
    source_recipe_id: string | null;
    batch_yield_qty: string;
    lines: Array<{
      id: string;
      child_template_id: string;
      qty_per_batch: string;
      unit: string;
      yield_loss_pct: string;
    }>;
  }> {
    const response = await this.request.get(
      `/api/v1/maker/recipes/${recipeId}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    if (!response.ok())
      throw new Error(`Failed to get maker recipe: ${await response.text()}`);
    return await response.json();
  }

  async deleteMakerRecipe(token: string, recipeId: string): Promise<void> {
    const response = await this.request.delete(
      `/api/v1/maker/recipes/${recipeId}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    if (!response.ok() && response.status() !== 404)
      throw new Error(
        `Failed to delete maker recipe: ${await response.text()}`,
      );
  }

  /**
   * Update maker module settings (PATCH /api/v1/maker/settings).
   * Used by tests to force deterministic create-on-shortage behavior.
   */
  async patchMakerSettings(
    token: string,
    data: Record<string, unknown>,
  ): Promise<void> {
    const response = await this.request.patch("/api/v1/maker/settings", {
      headers: { Authorization: `Bearer ${token}` },
      data,
    });
    if (!response.ok())
      throw new Error(
        `Failed to patch maker settings: ${await response.text()}`,
      );
  }

  /**
   * Reverse BoM edge: recipes consuming a template as an ingredient
   * (GET /api/v1/maker/bom/where-used).
   */
  async whereUsed(
    token: string,
    templateId: string,
  ): Promise<{
    items: Array<{
      recipe_id: string;
      recipe_name: string;
      output_template_id: string;
      output_template_name: string | null;
      qty_per_batch: string;
      unit: string;
    }>;
  }> {
    const response = await this.request.get(
      `/api/v1/maker/bom/where-used?template_id=${templateId}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    if (!response.ok())
      throw new Error(`Failed to get where-used: ${await response.text()}`);
    return await response.json();
  }

  async createProductionOrder(
    token: string,
    data: {
      output_template_id: string;
      planned_qty: string | number;
      output_location_id: string;
      production_date?: string | null;
      notes?: string | null;
      /** Acknowledge a shortage warning (the draft is created short on stock). */
      confirm_shortage?: boolean;
    },
  ): Promise<{
    id: string;
    status: string;
    total_cost: string | null;
    output_template_id: string;
    planned_qty: string;
  }> {
    const response = await this.request.post(
      "/api/v1/maker/production/orders",
      {
        headers: { Authorization: `Bearer ${token}` },
        data,
      },
    );
    if (!response.ok())
      throw new Error(
        `Failed to create production order: ${await response.text()}`,
      );
    return await response.json();
  }

  async listProductionOrders(
    token: string,
    filter?: { status?: string; output_template_id?: string },
  ): Promise<
    Array<{
      id: string;
      status: string;
      total_cost: string | null;
      output_template_id: string;
      planned_qty: string;
      output_location_id: string;
      created_at: string;
    }>
  > {
    const params = new URLSearchParams();
    if (filter?.status) params.set("status", filter.status);
    if (filter?.output_template_id)
      params.set("output_template_id", filter.output_template_id);
    const url = params.toString()
      ? `/api/v1/maker/production/orders?${params}`
      : "/api/v1/maker/production/orders";
    const response = await this.request.get(url, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok()) return [];
    const body = await response.json();
    // Endpoint is paginated ({items, total, ...}); older callers expect a
    // bare array.
    return Array.isArray(body) ? body : (body.items ?? []);
  }

  async getProductionOrder(
    token: string,
    orderId: string,
  ): Promise<{
    id: string;
    status: string;
    total_cost: string | null;
    output_template_id: string;
    planned_qty: string;
    lines: Array<{
      id: string;
      child_template_id: string;
      consumed_qty: string;
      unit: string;
      unit_cost_snapshot: string | null;
      cost_source: string | null;
    }>;
  }> {
    const response = await this.request.get(
      `/api/v1/maker/production/orders/${orderId}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(
        `Failed to get production order: ${await response.text()}`,
      );
    return await response.json();
  }

  async previewProduction(
    token: string,
    data: {
      output_template_id: string;
      planned_qty: string | number;
      output_location_id: string;
      production_date?: string | null;
      notes?: string | null;
    },
  ): Promise<{
    output_template_id: string;
    planned_qty: string;
    total_cost: string;
    entries: Array<{
      child_template_id: string;
      consumed_qty: string;
      unit: string;
      cost: string | null;
      percentage_of_total: string | null;
      cost_source: string;
    }>;
    missing_cost_lines: string[];
  }> {
    const response = await this.request.post(
      "/api/v1/maker/production/orders/preview",
      {
        headers: { Authorization: `Bearer ${token}` },
        data,
      },
    );
    if (!response.ok())
      throw new Error(`Failed to preview production: ${await response.text()}`);
    return await response.json();
  }

  async completeProductionOrder(
    token: string,
    orderId: string,
  ): Promise<{
    id: string;
    status: string;
    total_cost: string | null;
  }> {
    const response = await this.request.post(
      `/api/v1/maker/production/orders/${orderId}/complete`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(
        `Failed to complete production order: ${await response.text()}`,
      );
    return await response.json();
  }

  async cancelProductionOrder(
    token: string,
    orderId: string,
  ): Promise<{
    id: string;
    status: string;
  }> {
    const response = await this.request.post(
      `/api/v1/maker/production/orders/${orderId}/cancel`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(
        `Failed to cancel production order: ${await response.text()}`,
      );
    return await response.json();
  }

  async getCostBreakdown(
    token: string,
    templateId: string,
    qty: string | number,
  ): Promise<{
    output_template_id: string;
    planned_qty: string;
    total_cost: string;
    entries: Array<{
      child_template_id: string;
      consumed_qty: string;
      unit: string;
      cost: string | null;
      percentage_of_total: string | null;
      cost_source: string;
    }>;
    missing_cost_lines: string[];
  }> {
    const response = await this.request.get(
      `/api/v1/maker/breakdown/${templateId}?qty=${qty}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to get cost breakdown: ${await response.text()}`);
    return await response.json();
  }

  async computePricing(
    token: string,
    data: {
      template_id: string;
      produced_qty: string | number;
      target_margin_pct: string | number;
    },
  ): Promise<{
    template_id: string;
    produced_qty: string;
    total_cost: string;
    unit_cost: string;
    target_margin_pct: string;
    unit_sale_price: string;
  }> {
    const response = await this.request.post("/api/v1/maker/pricing/compute", {
      headers: { Authorization: `Bearer ${token}` },
      data,
    });
    if (!response.ok())
      throw new Error(`Failed to compute pricing: ${await response.text()}`);
    return await response.json();
  }

  async getMargin(
    token: string,
    templateId: string,
  ): Promise<{
    template_id: string;
    target_margin_pct: string;
    is_default: boolean;
  }> {
    const response = await this.request.get(
      `/api/v1/maker/pricing/margin/${templateId}`,
      {
        headers: { Authorization: `Bearer ${token}` },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to get margin: ${await response.text()}`);
    return await response.json();
  }

  async setMargin(
    token: string,
    templateId: string,
    targetMarginPct: string | number,
  ): Promise<{
    template_id: string;
    target_margin_pct: string;
    is_default: boolean;
  }> {
    const response = await this.request.put(
      `/api/v1/maker/pricing/margin/${templateId}`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: { target_margin_pct: targetMarginPct },
      },
    );
    if (!response.ok())
      throw new Error(`Failed to set margin: ${await response.text()}`);
    return await response.json();
  }
}
