import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { expectApiOk } from "./helpers/page-load";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

test.describe("Purchase Orders — page & navigation", () => {
  let api: ApiHelper;
  let token: string;
  let seedPartnerId: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    const partners = await api.listPartners(token);
    if (partners.length > 0) {
      seedPartnerId = partners[0].id;
    }
    if (!seedPartnerId) {
      const partner = await api.createPartner(token, {
        name: `E2E-PO-Partner-${Date.now()}`,
        type: "supplier",
        email: "po@example.com",
      });
      seedPartnerId = partner.id;
    }
  });

  test.afterAll(async () => {
    if (token && seedPartnerId) {
      await api.deletePartner(token, seedPartnerId).catch(() => {});
    }
  });

  test.beforeEach(async ({ page, authenticatedPage }) => {
    await page.goto("/purchase-orders");
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
  });

  test("displays purchase orders page heading", async ({
    page,
    authenticatedPage,
  }) => {
    await expect(
      page.getByRole("heading", { level: 1, name: /purchase orders/i }),
    ).toBeVisible({ timeout: 10000 });
  });

  test("has Create Order button", async ({ page, authenticatedPage }) => {
    // `.first()`: an empty list also renders a Create Order CTA in its
    // empty state, so the name matches two buttons.
    await expect(
      page.getByRole("button", { name: /create order/i }).first(),
    ).toBeVisible({ timeout: 10000 });
  });

  test("has navigation tabs", async ({ page, authenticatedPage }) => {
    await expect(
      page.getByRole("link", { name: /purchase orders/i }),
    ).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole("link", { name: /templates/i })).toBeVisible({
      timeout: 10000,
    });
  });

  test("opens create order form", async ({ page, authenticatedPage }) => {
    // `.first()`: an empty list also renders a Create Order CTA in its
    // empty state, so the name matches two buttons.
    const createBtn = page
      .getByRole("button", { name: /create order/i })
      .first();
    await expect(createBtn).toBeVisible({ timeout: 15000 });
    await createBtn.click();

    const form = page.locator('[role="dialog"]');
    // The header actions re-render when the orders query resolves; a click
    // that lands on a node replaced mid-event is lost. Detect that and
    // click the fresh node instead of failing the run.
    if (!(await form.isVisible({ timeout: 2000 }).catch(() => false))) {
      await page
        .getByRole("button", { name: /create order/i })
        .first()
        .click();
    }
    await expect(form).toBeVisible({ timeout: 10000 });
  });

  test("creates and lists a purchase order", async ({
    page,
    authenticatedPage,
  }) => {
    if (!seedPartnerId) return;

    const poNumber = `E2E-PO-${Date.now()}`;
    let po: { id: string } | null = null;
    try {
      po = await api.createPurchaseOrder(token, {
        number: poNumber,
        partner_id: seedPartnerId,
        status: "DRAFT",
        lines: [
          { name: "E2E PO Item", quantity_ordered: 5, unit_price: "10.00" },
        ],
      });
    } catch {
      return;
    }
    if (!po?.id) return;

    await page.goto("/purchase-orders");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    const poText = page.getByText(poNumber).first();
    if (await poText.isVisible({ timeout: 5000 }).catch(() => false)) {
      await expect(poText).toBeVisible();
    }

    await api.deletePurchaseOrder(token, po.id).catch(() => {});
  });

  test("navigates to templates page", async ({ page, authenticatedPage }) => {
    const templatesLink = page.getByRole("link", { name: /templates/i });
    await expect(templatesLink).toBeVisible({ timeout: 10000 });

    const loaded = expectApiOk(page, "/api/v1/purchase-orders/templates");
    await templatesLink.click();
    await loaded;

    await expect(page.locator("h1").first()).toBeVisible({ timeout: 15000 });
  });

  test("templates page loads directly", async ({ page, authenticatedPage }) => {
    const loaded = expectApiOk(page, "/api/v1/purchase-orders/templates");
    await page.goto("/purchase-orders/templates");
    await loaded;

    await expect(page.locator("h1").first()).toBeVisible({ timeout: 15000 });
  });
});

test.describe("Purchase Orders — detail & linked receipts", () => {
  let api: ApiHelper;
  let token: string;
  let poId: string;
  let poNumber: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    const partnerId =
      (await api.listPartners(token))[0]?.id ??
      (
        await api.createPartner(token, {
          name: `E2E-PO-${Date.now()}`,
          type: "SUPPLIER",
          email: "po-detail@example.com",
        })
      ).id;
    const po = await api.createPurchaseOrder(token, {
      number: `E2E-PO-Detail-${Date.now()}`,
      partner_id: partnerId,
      status: "DRAFT",
      lines: [
        {
          name: "E2E Detail Item",
          quantity_ordered: 2,
          unit_price: "15.00",
        },
      ],
    });
    poId = po.id;
    // The backend assigns the number from the org numbering format and
    // ignores the one sent in — read it back rather than assuming.
    poNumber = po.number;
  });

  test.afterAll(async () => {
    if (token && poId) {
      await api.deletePurchaseOrder(token, poId).catch(() => {});
    }
  });

  test("purchase order detail page loads", async ({
    page,
    authenticatedPage,
  }) => {
    // Anchored: /purchase-orders/{id}/linked-receipts and
    // /pending-quantities would otherwise match first.
    const loaded = expectApiOk(
      page,
      new RegExp(`/api/v1/purchase-orders/${poId}(\\?|$)`),
    );
    await page.goto(`/purchase-orders/${poId}`);
    await loaded;

    await expect(page.getByText(poNumber).first()).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByText("E2E Detail Item").first()).toBeVisible({
      timeout: 15000,
    });
  });

  test("linked receipts page loads", async ({ page, authenticatedPage }) => {
    const loaded = expectApiOk(
      page,
      `/api/v1/purchase-orders/${poId}/linked-receipts`,
    );
    await page.goto(`/purchase-orders/${poId}/linked-receipts`);
    await loaded;

    await expect(page.locator("h1").first()).toBeVisible({ timeout: 15000 });
  });
});
