import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { shownTitle } from "./helpers/document-title";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

test.describe("Documents — warehouse page", () => {
  let api: ApiHelper;
  let token: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
    await api.enableAllModules(token);
  });

  test.beforeEach(async ({ page, authenticatedPage }) => {
    await page.goto("/warehouse");
  });

  test("documents page loads with heading", async ({
    page,
    authenticatedPage,
  }) => {
    await expect(page.getByRole("heading").first()).toBeVisible({
      timeout: 15000,
    });
  });

  test("create document buttons are visible", async ({
    page,
    authenticatedPage,
  }) => {
    await expect(page.getByRole("heading").first()).toBeVisible({
      timeout: 15000,
    });
    await page.getByRole("button", { name: /new document/i }).click();
    await expect(
      page.getByRole("menuitem", { name: /receipt/i }).first(),
    ).toBeVisible();
  });

  test("has navigation bar links", async ({ page, authenticatedPage }) => {
    await expect(
      page
        .getByRole("link", {
          name: /warehouse|register|templates|settings|profile|documents/i,
        })
        .first(),
    ).toBeVisible({ timeout: 15000 });
  });
});

test.describe("Documents — profile settings", () => {
  let api: ApiHelper;
  let token: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
    await api.enableAllModules(token);
  });

  test.beforeEach(async ({ page, authenticatedPage }) => {
    await page.goto("/warehouse/settings");
  });

  test("profile page loads", async ({ page, authenticatedPage }) => {
    await expect(
      page.getByRole("heading", { level: 1, name: "Configuration" }),
    ).toBeVisible({ timeout: 15000 });
  });
});

test.describe("Documents — sub-pages", () => {
  let api: ApiHelper;
  let token: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
    await api.enableAllModules(token);
  });

  test("register page loads directly", async ({ page, authenticatedPage }) => {
    await page.goto("/warehouse/register");
    await expect(page.locator("h1, h2").first()).toBeVisible({
      timeout: 15000,
    });
  });

  test("scan page loads directly", async ({ page, authenticatedPage }) => {
    await page.goto("/warehouse/scan");
    await expect(page.locator("h1, h2").first()).toBeVisible({
      timeout: 15000,
    });
  });

  test("templates page loads directly", async ({ page, authenticatedPage }) => {
    await page.goto("/warehouse/templates");
    await expect(page.locator("h1, h2").first()).toBeVisible({
      timeout: 15000,
    });
  });
});

test.describe("Documents — detail page", () => {
  let api: ApiHelper;
  let token: string;
  let docId: string;
  let storageId: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;
    await api.enableAllModules(token);

    // Its own location: the first one of the shared tenant belongs to
    // whichever parallel spec deletes it first.
    storageId = (
      await api.createStorage(token, {
        name: `E2E-Documents-Detail-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      })
    ).id;
    const doc = await api.createIntDocumentWithStock(token, {
      source_location_id: storageId,
      target_location_id: storageId,
      lines: [{ name: "E2E-Doc-Item", expected_quantity: 1 }],
    });
    docId = doc.id;
  });

  test.afterAll(async () => {
    if (token && docId) {
      await api.cancelDocument(token, docId).catch(() => {});
      await api.deleteDocument(token, docId).catch(() => {});
    }
    if (token && storageId) {
      await api.deleteStorage(token, storageId).catch(() => {});
    }
  });

  test("document detail page loads", async ({ page, authenticatedPage }) => {
    await page.goto(`/warehouse/documents/${docId}`);
    await expect(page.locator("h1, h2").first()).toBeVisible({
      timeout: 15000,
    });
    await expect(page).toHaveURL(new RegExp(`/warehouse/documents/${docId}$`));
  });
});

test.describe("Documents — navigation", () => {
  let api: ApiHelper;
  let token: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
    await api.enableAllModules(token);
  });

  test.beforeEach(async ({ page, authenticatedPage }) => {
    await page.goto("/warehouse");
  });

  test("navigates to register page", async ({ page, authenticatedPage }) => {
    const registerLink = page.getByRole("link", { name: /register/i }).first();
    await expect(registerLink).toBeVisible({ timeout: 15000 });
    await registerLink.click();
    await page.waitForURL("**/warehouse/register", { timeout: 15000 });
    await expect(page.locator("h1, h2").first()).toBeVisible({
      timeout: 15000,
    });
  });
});

// ── New: CRUD flow, state transitions, corrections, search ──────────────

test.describe("Documents — state transitions via UI", () => {
  // The Plan test moves the document that the next test inspects.
  test.describe.configure({ mode: "serial" });
  let api: ApiHelper;
  let token: string;
  let docId: string;
  let plannedDocId: string;
  let storageId: string;

  // A local calendar date, as the detail page's todayIso() compares it: a UTC
  // slice is still today east of UTC after midnight. A week ahead stays ahead
  // even when the run crosses midnight between setup and assertion.
  const aWeekAhead = () => {
    const d = new Date();
    d.setDate(d.getDate() + 7);
    const month = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${d.getFullYear()}-${month}-${day}`;
  };

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;
    await api.enableAllModules(token);

    // Its own location: the first one of the shared tenant belongs to
    // whichever parallel spec deletes it first.
    storageId = (
      await api.createStorage(token, {
        name: `E2E-Documents-States-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      })
    ).id;

    const doc = await api.createIntDocumentWithStock(token, {
      source_location_id: storageId,
      target_location_id: storageId,
      lines: [{ name: "E2E-State-Transition-Item", expected_quantity: 5 }],
    });
    docId = doc.id;
    // Only a document dated in the future can be planned (confirmed) first;
    // any other draft is posted at once.
    const planned = await api.createIntDocumentWithStock(token, {
      source_location_id: storageId,
      target_location_id: storageId,
      lines: [{ name: "E2E-State-Planned-Item", expected_quantity: 2 }],
      scheduled_date: aWeekAhead(),
    });
    plannedDocId = planned.id;
  });

  test.afterAll(async () => {
    for (const id of [docId, plannedDocId]) {
      if (!token || !id) continue;
      await api.cancelDocument(token, id).catch(() => {});
      await api.deleteDocument(token, id).catch(() => {});
    }
    if (token && storageId) {
      await api.deleteStorage(token, storageId).catch(() => {});
    }
  });

  test("a transfer draft offers Move stock, not a separate Confirm", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto(`/warehouse/documents/${docId}`);
    expect((await api.getDocument(token, docId)).status).toBe("DRAFT");
    await expect(
      page.getByRole("button", { name: "Move stock", exact: true }),
    ).toBeVisible({ timeout: 15000 });
    await expect(page.getByRole("button", { name: /^confirm$/i })).toHaveCount(
      0,
    );
    // Not dated ahead, so there is nothing to plan.
    await expect(
      page.getByRole("button", { name: "More actions" }),
    ).toHaveCount(0);
  });

  test("a draft dated ahead is planned through More actions", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto(`/warehouse/documents/${plannedDocId}`);
    await page.getByRole("button", { name: "More actions" }).click();
    await page.getByRole("button", { name: "Plan", exact: true }).click();

    const dialog = page.getByRole("alertdialog").or(page.getByRole("dialog"));
    await dialog.getByRole("button", { name: /^confirm$/i }).click();

    await expect
      .poll(async () => (await api.getDocument(token, plannedDocId)).status, {
        timeout: 15000,
      })
      .toBe("CONFIRMED");
  });

  test("shows Execute button after confirm", async ({
    page,
    authenticatedPage,
  }) => {
    expect((await api.getDocument(token, plannedDocId)).status).toBe(
      "CONFIRMED",
    );

    await page.goto(`/warehouse/documents/${plannedDocId}`);
    const executeBtn = page
      .getByRole("button", { name: /pick items/i })
      .first();
    await expect(executeBtn).toBeVisible({ timeout: 15000 });
  });

  test("cancels a DRAFT document via API and verifies", async () => {
    const draftDoc = await api.createDocument(token, {
      type: "INT",
      source_location_id: storageId,
      target_location_id: storageId,
      lines: [{ name: "E2E-Cancel-Test", expected_quantity: 1 }],
    });
    expect(draftDoc.id).toBeTruthy();

    await api.cancelDocument(token, draftDoc.id);
    const cancelled = await api.getDocument(token, draftDoc.id);
    expect(cancelled.status).toBe("CANCELLED");

    await api.deleteDocument(token, draftDoc.id).catch(() => {});
  });
});

test.describe("Documents — CRUD via API + detail verification", () => {
  let api: ApiHelper;
  let token: string;
  let storageId: string;
  const createdDocIds: string[] = [];

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;
    await api.enableAllModules(token);

    // Its own location: the first one of the shared tenant belongs to
    // whichever parallel spec deletes it first.
    storageId = (
      await api.createStorage(token, {
        name: `E2E-Documents-CRUD-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      })
    ).id;
  });

  test.afterAll(async () => {
    for (const id of createdDocIds) {
      await api.cancelDocument(token, id).catch(() => {});
      await api.deleteDocument(token, id).catch(() => {});
    }
    if (token && storageId) {
      await api.deleteStorage(token, storageId).catch(() => {});
    }
  });

  test("creates INT document via API and detail loads", async ({
    page,
    authenticatedPage,
  }) => {
    const doc = await api.createDocument(token, {
      type: "INT",
      source_location_id: storageId,
      target_location_id: storageId,
      lines: [{ name: "E2E-CRUD-Item", expected_quantity: 10 }],
    });
    createdDocIds.push(doc.id);
    expect(doc.id).toBeTruthy();
    expect(doc.number).toBeTruthy();

    await page.goto(`/warehouse/documents/${doc.id}`);
    await expect(page.locator("h1, h2").first()).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByText(shownTitle(doc)).first()).toBeVisible({
      timeout: 15000,
    });
  });

  test("updates document notes via API", async () => {
    const doc = await api.createDocument(token, {
      type: "INT",
      source_location_id: storageId,
      target_location_id: storageId,
      lines: [{ name: "E2E-Update-Item", expected_quantity: 1 }],
    });
    createdDocIds.push(doc.id);

    const updated = await api.updateDocument(token, doc.id, {
      notes: "E2E updated notes",
    });
    expect(updated.notes).toBe("E2E updated notes");
    expect((await api.getDocument(token, doc.id)).notes).toBe(
      "E2E updated notes",
    );
  });

  test("lists documents and finds created one", async () => {
    const doc = await api.createDocument(token, {
      type: "INT",
      source_location_id: storageId,
      target_location_id: storageId,
      lines: [{ name: "E2E-List-Item", expected_quantity: 1 }],
    });
    createdDocIds.push(doc.id);

    const docs = await api.listDocuments(token);
    expect(docs.map((d) => d.id)).toContain(doc.id);
  });

  test("gets document register", async () => {
    const register = await api.getDocumentRegister(token);
    expect(register).toBeTruthy();
  });
});

test.describe("Documents — corrections", () => {
  let api: ApiHelper;
  let token: string;
  let completedDocId: string;
  let storageId: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;
    await api.enableAllModules(token);

    // Its own location: the first one of the shared tenant belongs to
    // whichever parallel spec deletes it first.
    storageId = (
      await api.createStorage(token, {
        name: `E2E-Documents-Corrections-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      })
    ).id;

    const item = await api.createItem(token, {
      name: "E2E-Correction-Item",
      quantity: 10,
      location_id: storageId,
    });
    // An adjustment cannot be corrected — its lines are already differences,
    // so a mistake in one is a new adjustment. A receipt is correctable, and
    // that is the document this spec is about. The partner stays behind with
    // the completed receipt, and a partner name is unique per type, so a fixed
    // name would fail every run after the first on the same database.
    const partner = await api.createPartner(token, {
      name: `E2E-Correction-Supplier-${Date.now()}`,
      type: "SUPPLIER",
    });
    const doc = await api.createDocument(token, {
      type: "IN",
      partner_id: partner.id,
      target_location_id: storageId,
      lines: [{ item_id: item.id, expected_quantity: 10 }],
    });
    await api.confirmDocument(token, doc.id);

    await api.completeDocument(token, doc.id);
    completedDocId = doc.id;
  });

  test.afterAll(async () => {
    if (token && completedDocId) {
      await api.cancelDocument(token, completedDocId).catch(() => {});
      await api.deleteDocument(token, completedDocId).catch(() => {});
    }
    if (token && storageId) {
      await api.deleteStorage(token, storageId).catch(() => {});
    }
  });

  test("creates a correction document", async () => {
    const correction = await api.createCorrection(token, {
      corrects_document_id: completedDocId,
      reason_code: "OTHER",
      notes: "E2E correction",
      lines: [
        {
          original_line_number: 1,
          quantity_delta: -2,
          notes: "E2E correction note",
        },
      ],
    });
    expect(correction.id).toBeTruthy();

    const corrections = await api.listCorrections(token, completedDocId);
    expect(corrections.map((c) => c.id)).toContain(correction.id);
  });
});

test.describe("Documents — register page", () => {
  let api: ApiHelper;
  let token: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
    await api.enableAllModules(token);
  });

  test("register page shows document list", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/warehouse/register");
    await expect(page.locator("h1, h2").first()).toBeVisible({
      timeout: 15000,
    });
  });

  test("register API returns data", async () => {
    const register = await api.getDocumentRegister(token);
    expect(register).toBeTruthy();
  });
});

test.describe("Documents — inline partner creation", () => {
  let api: ApiHelper;
  let token: string;
  const createdPartnerIds: string[] = [];

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;
    await api.enableAllModules(token);
  });

  test.afterAll(async () => {
    for (const id of createdPartnerIds) {
      await api.deletePartner(token, id).catch(() => {});
    }
  });

  test("creates a new partner inline from document form", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/warehouse");

    await page.getByRole("button", { name: /new document/i }).click();
    await page
      .getByRole("menuitem", { name: /receipt/i })
      .first()
      .click();

    const partnerName = `E2E-Inline-Partner-${Date.now()}`;
    const form = page.getByRole("dialog");
    const partnerField = form
      .getByRole("combobox", { name: /partner/i })
      .first();
    await partnerField.click();
    await page
      .getByRole("textbox", { name: /search/i })
      .last()
      .fill(partnerName);
    await page
      .getByText(/create new partner/i)
      .first()
      .click();

    await page.getByLabel(/^name/i).fill(partnerName);
    const created = page.waitForResponse(
      (r) =>
        r.url().includes("/api/v1/partners") && r.request().method() === "POST",
    );
    await page.getByTestId("partner-inline-create-submit").click();
    const body = await (await created).json();
    createdPartnerIds.push(body.id);

    const found = await api.listPartners(
      token,
      `search=${partnerName}&limit=5`,
    );
    expect(found.map((p) => p.name)).toContain(partnerName);
    await expect(partnerField).toContainText(partnerName);
  });
});
