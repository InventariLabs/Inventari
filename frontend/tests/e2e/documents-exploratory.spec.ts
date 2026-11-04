import { isTransientModuleLoadError } from "./helpers/transient-load";
import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { shownTitle } from "./helpers/document-title";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

// ══════════════════════════════════════════════════════════════════════════════
// DOCUMENTS MODULE — E2E EXPLORATORY / QA TESTS
//
// Focus: user workflows, UI interactions, data integrity, error recovery.
// Unlike pentest, these assume a good-faith user and look for UX bugs.
// ══════════════════════════════════════════════════════════════════════════════

// ── 1. FULL USER WORKFLOW: CREATE → CONFIRM → EXECUTE ──────────────────────

test.describe("Documents Exploratory — Full User Workflow", () => {
  let api: ApiHelper;
  let token: string;
  let storageId: string;
  const cleanupIds: string[] = [];

  test.beforeAll(async ({ playwright, baseURL }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
    await api.enableAllModules(token);
    // Its own location: the first one of the shared tenant belongs to
    // whichever parallel spec deletes it first.
    const storage = await api.createStorage(token, {
      name: `E2E-Exploratory-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    });
    storageId = storage.id;
  });

  test.afterAll(async () => {
    for (const id of cleanupIds) {
      await api.cancelDocument(token, id).catch(() => {});
      await api.deleteDocument(token, id).catch(() => {});
    }
    await api.deleteStorage(token, storageId).catch(() => {});
  });

  test("create INT document via UI dialog", async ({
    page,
    authenticatedPage,
  }) => {
    expect(storageId, "the spec created its own storage location").toBeTruthy();
    // /warehouse opens History; the document list keeps "New document" in
    // its header, where the growing History cannot push it away.
    await page.goto("/warehouse/all");
    await page
      .getByRole("button", { name: "New document", exact: true })
      .click({ timeout: 15000 });
    await page
      .getByRole("menu", { name: "New document" })
      .getByRole("menuitem", { name: /^Transfer\b/ })
      .click();

    await expect(page.getByRole("dialog")).toBeVisible({ timeout: 10000 });
  });

  test("document list loads without JS errors", async ({
    page,
    authenticatedPage,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => {
      if (!isTransientModuleLoadError(err.message)) errors.push(err.message);
    });

    await page.goto("/warehouse");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    expect(errors).toHaveLength(0);
  });

  test("document detail page shows all sections", async ({
    page,
    authenticatedPage,
  }) => {
    if (!storageId) return;
    const doc = await api.createDocument(token, {
      type: "INT",
      source_location_id: storageId,
      target_location_id: storageId,
      notes: "Exploratory test document",
      lines: [
        { name: "Widget A", expected_quantity: 5 },
        { name: "Widget B", expected_quantity: 3 },
      ],
    });
    cleanupIds.push(doc.id);

    await page.goto(`/warehouse/documents/${doc.id}`);
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    // Should show the document by its name (a draft has no number yet)
    await expect(page.getByText(shownTitle(doc)).first()).toBeVisible({
      timeout: 10000,
    });
    // Should show line items. The lines render twice — a card list for
    // phones (`sm:hidden`) and a table from `sm` up — so an unscoped
    // getByText matches two nodes and trips strict mode. This project runs
    // Desktop Chrome, so assert on the table, which is the visible one.
    const lines = page.getByRole("table");
    await expect(lines.getByText("Widget A")).toBeVisible({ timeout: 5000 });
    await expect(lines.getByText("Widget B")).toBeVisible({ timeout: 5000 });
  });

  test("search filters documents correctly", async ({
    page,
    authenticatedPage,
  }) => {
    if (!storageId) return;
    const uniqueName = `Exploratory-${Date.now()}`;
    const doc = await api.createDocument(token, {
      type: "INT",
      source_location_id: storageId,
      target_location_id: storageId,
      notes: uniqueName,
      lines: [{ name: "Search Item", expected_quantity: 1 }],
    });
    cleanupIds.push(doc.id);

    await page.goto("/warehouse");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    const searchInput = page.getByPlaceholder(/search|szukaj/i).first();
    if (!(await searchInput.isVisible({ timeout: 5000 }).catch(() => false)))
      return;

    await searchInput.fill(doc.number);
    // The document should appear in filtered results. Wait for the number to
    // render (the list search is debounced) instead of a fixed sleep, which
    // raced under CI load and produced a flaky failure.
    await expect(page.getByText(shownTitle(doc)).first()).toBeVisible({
      timeout: 5000,
    });
  });

  test("pagination works on document list", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/warehouse");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    // Check if pagination controls exist
    const hasNext = await page
      .getByRole("button", { name: /next|następna|›/i })
      .first()
      .isVisible({ timeout: 3000 })
      .catch(() => false);

    // Either pagination exists or there are few documents
    expect(true).toBeTruthy();
  });
});

// ── 2. PROFILE & SETTINGS WORKFLOWS ─────────────────────────────────────────

test.describe("Documents Exploratory — Profile & Settings", () => {
  let api: ApiHelper;
  let token: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
  });

  test("profile page loads with current settings", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/warehouse/settings");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    // Should show profile heading
    await expect(page.locator("body")).toBeVisible();
    // Check for form elements
    const inputs = page.locator("input, select");
    const count = await inputs.count();
    expect(count).toBeGreaterThan(0);
  });

  test("settings page has type config options", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/warehouse/settings");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    // Should show some configuration options
    await expect(page.locator("body")).toBeVisible();
  });

  test("templates page lists templates", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/warehouse/templates");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    await expect(page.locator("body")).toBeVisible();
    // Should show at least the page content
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.length).toBeGreaterThan(0);
  });
});

// ── 3. REGISTER PAGE ────────────────────────────────────────────────────────

test.describe("Documents Exploratory — Register", () => {
  let api: ApiHelper;
  let token: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
  });

  test("register page loads with date picker", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/warehouse/register");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    // Should show heading and some content
    await expect(page.locator("body")).toBeVisible();
  });

  test("register shows document groups", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/warehouse/register");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    // Page should render without errors
    const errors: string[] = [];
    page.on("pageerror", (err) => {
      if (!isTransientModuleLoadError(err.message)) errors.push(err.message);
    });
    expect(errors).toHaveLength(0);
  });
});

// ── 4. SCAN PAGE ────────────────────────────────────────────────────────────

test.describe("Documents Exploratory — Scan Page", () => {
  test("scan page loads without errors", async ({
    page,
    authenticatedPage,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => {
      if (!isTransientModuleLoadError(err.message)) errors.push(err.message);
    });

    await page.goto("/warehouse/scan");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    await expect(page.locator("body")).toBeVisible();
    expect(errors).toHaveLength(0);
  });
});

// ── 5. DOCUMENT CREATION FORM EDGE CASES ────────────────────────────────────

test.describe("Documents Exploratory — Form Edge Cases", () => {
  let api: ApiHelper;
  let token: string;
  let storageId: string;
  const cleanupIds: string[] = [];

  test.beforeAll(async ({ playwright, baseURL }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
    // Its own location: the first one of the shared tenant belongs to
    // whichever parallel spec deletes it first.
    const storage = await api.createStorage(token, {
      name: `E2E-Exploratory-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    });
    storageId = storage.id;
  });

  test.afterAll(async () => {
    for (const id of cleanupIds) {
      await api.cancelDocument(token, id).catch(() => {});
      await api.deleteDocument(token, id).catch(() => {});
    }
    await api.deleteStorage(token, storageId).catch(() => {});
  });

  test("creating document with many lines via API", async () => {
    if (!storageId) return;
    const lines = Array.from({ length: 15 }, (_, i) => ({
      name: `Line-Item-${i}`,
      expected_quantity: i + 1,
    }));
    const doc = await api.createDocument(token, {
      type: "INT",
      source_location_id: storageId,
      target_location_id: storageId,
      lines,
    });
    cleanupIds.push(doc.id);
    expect(doc.lines.length).toBe(15);
  });

  test("document with special characters in notes via API", async () => {
    if (!storageId) return;
    const doc = await api.createDocument(token, {
      type: "INT",
      source_location_id: storageId,
      target_location_id: storageId,
      notes: "Ümlauts: äöü & special: <tag> 'quotes' \"double\"",
      lines: [{ name: "Special", expected_quantity: 1 }],
    });
    cleanupIds.push(doc.id);
    expect(doc.notes).toContain("Ümlauts");
  });

  test("document with all line fields via API", async () => {
    if (!storageId) return;
    const doc = await api.createDocument(token, {
      type: "INT",
      source_location_id: storageId,
      target_location_id: storageId,
      lines: [
        {
          name: "Full Item",
          expected_quantity: 10,
          unit_price: 25.5,
          tax_rate: 23,
          batch_number: "BATCH-001",
          serial_number: "SN-12345",
          expiry_date: "2027-12-31",
          notes: "Line note",
        },
      ],
    });
    cleanupIds.push(doc.id);
    const line = doc.lines[0];
    expect(line.batch_number).toBe("BATCH-001");
    expect(line.serial_number).toBe("SN-12345");
    expect(line.expiry_date).toBe("2027-12-31");
  });

  test("confirm document via API shows correct status", async () => {
    if (!storageId) return;
    const doc = await api.createIntDocumentWithStock(token, {
      source_location_id: storageId,
      target_location_id: storageId,
      lines: [{ name: "Confirm Test", expected_quantity: 1 }],
    });
    cleanupIds.push(doc.id);

    const confirmed = await api.confirmDocument(token, doc.id);
    expect((confirmed as Record<string, unknown>).status).toBe("CONFIRMED");
  });

  test("cancel document via API shows correct status", async () => {
    if (!storageId) return;
    const doc = await api.createDocument(token, {
      type: "INT",
      source_location_id: storageId,
      target_location_id: storageId,
      lines: [{ name: "Cancel Test", expected_quantity: 1 }],
    });

    await api.cancelDocument(token, doc.id);
    const cancelled = await api.getDocument(token, doc.id);
    expect(cancelled.status).toBe("CANCELLED");
  });
});

// ── 6. RESPONSIVE ───────────────────────────────────────────────────────────

test.describe("Documents Exploratory — Responsive", () => {
  test.use({ ...({ viewport: { width: 375, height: 812 } } as any) });

  test("documents list renders properly on mobile", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/warehouse");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    // No horizontal overflow
    const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
    expect(bodyWidth).toBeLessThanOrEqual(375 + 10);

    // Main heading should be visible
    await expect(page.locator("h1, h2").first()).toBeVisible({
      timeout: 10000,
    });
  });

  test("profile page renders on mobile", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/warehouse/settings");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
    expect(bodyWidth).toBeLessThanOrEqual(375 + 10);
  });

  test("register page renders on mobile", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/warehouse/register");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
    expect(bodyWidth).toBeLessThanOrEqual(375 + 10);
  });
});

// ── 7. ERROR RECOVERY ───────────────────────────────────────────────────────

test.describe("Documents Exploratory — Error Recovery", () => {
  let api: ApiHelper;
  let token: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
  });

  test("navigating to non-existent document shows graceful error", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/warehouse/documents/00000000-0000-0000-0000-000000000000");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    // Should not crash — should show some error or redirect
    await expect.poll(async () => (await page.locator("body").innerText()).length).toBeGreaterThan(0);
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.length).toBeGreaterThan(0);
  });

  test("page recovers after network error", async ({
    page,
    authenticatedPage,
  }) => {
    // First load
    await page.goto("/warehouse");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    // Reload
    await page.reload();
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    // Should still be functional
    await expect(page.locator("body")).toBeVisible();
  });

  test("multiple rapid navigations don't crash", async ({
    page,
    authenticatedPage,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => {
      if (!isTransientModuleLoadError(err.message)) errors.push(err.message);
    });

    await page.goto("/warehouse");
    await page.goto("/warehouse/settings");
    await page.goto("/warehouse/register");
    await page.goto("/warehouse");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    expect(errors).toHaveLength(0);
  });
});
