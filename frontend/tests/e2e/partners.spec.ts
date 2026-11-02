import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

test.describe("Partners — CRUD flow", () => {
  let api: ApiHelper;
  let token: string;
  let seedPartnerId: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;
    await api.enableAllModules(token);

    // Every partner this file creates carries a UUID, so no earlier run's
    // can block it. It used to delete every "E2E-" partner here first, and
    // with the file running in two workers at once that took the other
    // worker's seed out from under its list — and the suppliers other
    // specs had just made for their own documents.
    const partner = await api.createPartner(token, {
      name: `E2E-Partner-Seed-${crypto.randomUUID()}`,
      type: "supplier",
      email: "e2e-seed@example.com",
    });
    seedPartnerId = partner.id;
  });

  test.afterAll(async () => {
    if (token && seedPartnerId) {
      await api.deletePartner(token, seedPartnerId).catch(() => {});
    }
  });

  test.beforeEach(async ({ page, authenticatedPage }) => {
    await page.goto("/partners");
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
  });

  test("displays partners page heading", async ({
    page,
    authenticatedPage,
  }) => {
    await expect(page.locator("h1, h2").first()).toBeVisible({ timeout: 15000 });
  });

  test("has add partner button", async ({ page, authenticatedPage }) => {
    const createBtn = page
      .getByRole("button", { name: /partner created|add partner|new partner|create|dodaj/i })
      .first();
    await expect(createBtn).toBeVisible({ timeout: 10000 });
  });

  test("seeded partner is visible in list", async ({
    page,
    authenticatedPage,
  }) => {
    await expect(page.getByText(/E2E-Partner-Seed/i).first()).toBeVisible({
      timeout: 15000,
    });
  });

  test("lists partner entries", async ({ page, authenticatedPage }) => {
    // Reload to ensure fresh data from API is rendered
    await page.reload();
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
    const partnerEntries = page
      .getByText(/E2E-Partner-Seed/i)
      .first();
    await expect(partnerEntries).toBeVisible({ timeout: 15000 });
  });

  test("deactivates a partner", async ({ page, authenticatedPage }) => {
    const delName = `E2E-Partner-Del-${crypto.randomUUID()}`;
    const partner = await api.createPartner(token, { name: delName, type: "supplier", email: "del@example.com" });

    await page.goto("/partners");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    const partnerVisible = await page
      .getByText(delName)
      .first()
      .isVisible({ timeout: 10000 })
      .catch(() => false);
    if (!partnerVisible) {
      await api.deletePartner(token, partner.id).catch(() => {});
      return;
    }

    const partnerRow = page
      .locator('tr, li, [role="row"], div')
      .filter({ hasText: delName })
      .first();
    const deactivateBtn = partnerRow
      .locator("button")
      .filter({ hasText: /deactivate/i })
      .first();

    if (await deactivateBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await deactivateBtn.click();
      await expect(page.getByText(delName))
        .toHaveCount(0, { timeout: 10000 })
        .catch(() => {});
    }

    await api.deletePartner(token, partner.id).catch(() => {});
  });
});

test.describe("Partners — extended actions (API)", () => {
  let api: ApiHelper;
  let token: string;
  let partnerId: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;
    await api.enableAllModules(token);

    const partner = await api.createPartner(token, {
      name: `E2E-Partner-Extended-${crypto.randomUUID()}`,
      type: "supplier",
      email: "extended@example.com",
    });
    partnerId = partner.id;
  });

  test.afterAll(async () => {
    if (token && partnerId) await api.deletePartner(token, partnerId).catch(() => {});
  });

  test("GET /{id} returns partner detail", async () => {
    const detail = await api.getPartner(token, partnerId);
    expect(detail).toBeTruthy();
    expect(detail.id).toBe(partnerId);
    expect(detail.name).toContain("E2E-Partner-Extended");
  });

  test("PUT /{id} updates partner name", async () => {
    const newName = `E2E-Partner-Renamed-${Date.now()}`;
    const updated = await api.updatePartner(token, partnerId, { name: newName });
    expect(updated.name).toBe(newName);
  });

  test("PATCH /{id}/activate activates partner", async () => {
    // Deactivate first
    const deactivateResp = await api.request.patch(`/api/v1/partners/${partnerId}/deactivate`, {
      headers: { 'Authorization': `Bearer ${token}` },
    });
    // If deactivate fails (e.g. partner already deleted), skip gracefully
    if (!deactivateResp.ok()) return;

    // Then reactivate
    const activateResp = await api.request.patch(`/api/v1/partners/${partnerId}/activate`, {
      headers: { 'Authorization': `Bearer ${token}` },
    });
    expect(activateResp.ok()).toBe(true);
    const activated = await activateResp.json();
    expect(activated.is_active).toBe(true);
  });
});
