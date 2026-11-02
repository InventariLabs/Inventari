import { request } from "@playwright/test";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * Global setup runs once before all tests.
 * - Enables all optional modules
 * - Seeds baseline test data (storage, category, 3 products) shared across specs
 *   IDs are exposed via process.env so individual specs can reference them.
 *
 * Note: browser authentication is no longer done here — each worker gets
 * its own session_id via the per-test login in fixtures/auth.ts.
 */
async function globalSetup() {
  console.log("--- GLOBAL SETUP START ---");
  const baseURL = process.env.VITE_API_URL || "http://127.0.0.1:5173";

  const context = await request.newContext({ baseURL });

  try {
    const api = new ApiHelper(context);

    // 1. Authenticate via API (for seeding only)
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    const token = authData.access_token;

    // 1b. A freshly reset database has not completed onboarding, and every
    // route then redirects to the workflow wizard — nearly the whole suite
    // would fail regardless of what it tests. Idempotent: 409 (already
    // completed) is accepted.
    console.log("Completing onboarding if needed...");
    await api.completeOnboarding(token);

    // 2. Enable all modules required for specs
    console.log("Enabling optional modules...");
    await api.enableAllModules(token);

    // 2b. Set language to English so UI renders consistently in tests
    await api.setUserLanguage(token, "en");

    // 2c. Permanent deletion is off by default on audited profiles
    // (clean_core, equipment_wms), and the seeded test org runs on
    // one of them. Set the explicit flag so the purge specs exercise the
    // happy path; the explicit setting wins over the profile default, so a
    // spec that switches the org profile cannot take it away again.
    await api.updateOrganizationSettings(token, {
      allow_permanent_delete: true,
    });

    // 3. Clean up any leftover E2E data from previous runs (idempotent setup)
    console.log("Cleaning up leftover E2E data...");

    // Delete documents FIRST — they have FK to storage_locations
    const existingDocuments = await api.listDocuments(token);
    for (const d of existingDocuments) {
      if (d.number?.startsWith("E2E-")) {
        await api.cancelDocument(token, d.id).catch(() => {});
        await api.deleteDocument(token, d.id).catch(() => {});
      }
    }

    const existingStockTakes = await api.listStockTakes(token);
    for (const st of existingStockTakes) {
      if (st.name.startsWith("E2E-")) {
        await api.deleteStockTake(token, st.id).catch(() => {});
      }
    }

    const existingStorages = await api.listStorages(token);
    for (const s of existingStorages) {
      if (s.name.startsWith("E2E-") || s.name.startsWith("Z_Test ")) {
        // Delete items in storage first (may include related labels, stock quants, etc.)
        const items = await api.listItems(token, `location_id=${s.id}`);
        for (const item of items) {
          await api.deleteItem(token, item.id).catch(() => {});
        }
        await api.deleteStorage(token, s.id).catch(() => {});
      }
    }
    const existingCategories = await api.listCategories(token);
    for (const c of existingCategories) {
      if (
        (c.name as string).startsWith("E2E-") ||
        (c.name as string).startsWith("Z_Test ")
      ) {
        await api.deleteCategory(token, c.id).catch(() => {});
      }
    }

    // Clean up other E2E leftover entities that could interfere
    const existingShoppingLists = await api.listShoppingLists(token);
    for (const sl of existingShoppingLists) {
      if ((sl.name || (sl as any).title || "").includes("E2E-")) {
        await api.deleteShoppingList(token, sl.id).catch(() => {});
      }
    }
    const existingWebhooks = await api.listWebhooks(token);
    for (const w of existingWebhooks) {
      if (w.name.startsWith("E2E-")) {
        await api.deleteWebhook(token, w.id).catch(() => {});
      }
    }
    const existingWorkflows = await api.listWorkflows(token);
    for (const w of existingWorkflows) {
      if (w.name.startsWith("E2E-")) {
        await api.deleteWorkflow(token, w.id).catch(() => {});
      }
    }

    const existingPartners = await api.listPartners(token, "limit=1000");
    for (const p of existingPartners) {
      if (p.name.startsWith("E2E-") || p.name.startsWith("Z_Test ")) {
        await api.deletePartner(token, p.id).catch(() => {});
      }
    }

    const existingApiKeys = await api.listApiKeys(token);
    for (const k of existingApiKeys) {
      if (k.name.startsWith("Test API Key")) {
        await api.deleteApiKey(token, k.id).catch(() => {});
      }
    }

    // Also try to delete E2E-Kitchen storage directly if it still lingers
    const storagesAfter = await api.listStorages(token);
    for (const s of storagesAfter) {
      if (s.name === "E2E-Kitchen") {
        const items = await api.listItems(token, `location_id=${s.id}`);
        for (const item of items) {
          await api.deleteItem(token, item.id).catch(() => {});
        }
        await api.deleteStorage(token, s.id).catch(() => {});
      }
    }

    // 4. Seed baseline data used by multiple specs
    console.log("Seeding baseline test data...");

    let storage;
    try {
      storage = await api.createStorage(token, { name: "E2E-Kitchen" });
    } catch (e: any) {
      if (e.message?.includes("already exists")) {
        // Fallback: find and reuse existing
        const storages = await api.listStorages(token);
        const existing = storages.find(
          (s: { name: string }) => s.name === "E2E-Kitchen",
        );
        if (existing) storage = existing;
      } else {
        throw e;
      }
    }
    if (!storage)
      throw new Error("Could not create or find E2E-Kitchen storage");
    process.env.E2E_STORAGE_ID = storage.id;
    console.log(`  Storage: E2E-Kitchen (${storage.id})`);

    let category;
    try {
      category = await api.createCategory(token, { name: "E2E-Dairy" });
    } catch (e: any) {
      if (e.message?.includes("already exists")) {
        const cats = await api.listCategories(token);
        const existing = (cats as Array<{ id: string; name: string }>).find(
          (c: { name: string }) => c.name === "E2E-Dairy",
        );
        if (existing) category = existing;
      } else {
        throw e;
      }
    }
    if (!category)
      throw new Error("Could not create or find E2E-Dairy category");
    process.env.E2E_CATEGORY_ID = category.id;
    console.log(`  Category: E2E-Dairy (${category.id})`);

    const today = new Date();
    const in5Days = new Date(today);
    in5Days.setDate(today.getDate() + 5);
    const past5Days = new Date(today);
    past5Days.setDate(today.getDate() - 5);

    const normal = await api.createItem(token, {
      name: "E2E-Normal-Item",
      quantity: 20,
      location_id: storage.id,
      category_id: category.id,
    });
    process.env.E2E_ITEM_NORMAL_ID = normal.id;

    const expiring = await api.createItem(token, {
      name: "E2E-Expiring-Item",
      quantity: 10,
      location_id: storage.id,
      category_id: category.id,
      expiry_date: in5Days.toISOString().split("T")[0],
    });
    process.env.E2E_ITEM_EXPIRING_ID = expiring.id;

    const expired = await api.createItem(token, {
      name: "E2E-Expired-Item",
      quantity: 5,
      location_id: storage.id,
      category_id: category.id,
      expiry_date: past5Days.toISOString().split("T")[0],
    });
    process.env.E2E_ITEM_EXPIRED_ID = expired.id;

    console.log("  Seeded 3 baseline items (normal, expiring, expired)");

    console.log("--- GLOBAL SETUP COMPLETE ---");
  } catch (err) {
    console.error("Failed in globalSetup:", err);
    throw err;
  } finally {
    await context.dispose();
  }
}

export default globalSetup;
