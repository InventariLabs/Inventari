import { test, expect } from "./fixtures/polish";
import { ApiHelper } from "./helpers/api";
import { expectApiOk } from "./helpers/page-load";
import { expectNoRawI18nKeys } from "./helpers/i18n-keys";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * The one project that renders the interface in the language the product is
 * actually used in. Every other project forces en-US so text selectors stay
 * stable, which means 588 e2e cases never see a Polish string.
 *
 * Selectors here are roles and test ids on purpose — asserting Polish copy
 * would just duplicate the translation files into the test suite. What is
 * asserted instead is that the page works and that nothing renders as a raw
 * translation key.
 */

// Pinned to one worker: fullyParallel would otherwise spread these four tests
// across workers and run the fixture-seeding beforeAll once per worker, on the
// same account. That races — an observed run had the shopping list vanish
// between its creation and the item being added to it.
test.describe.configure({ mode: "serial" });

test.describe("Polish UI on a phone", () => {
  let api: ApiHelper;
  let token: string;
  let listId: string;
  let documentId: string;
  const listName = `E2E-Lista-${Date.now()}`;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    // The shopping-lists module is enabled by globalSetup. This spec runs in
    // the `pl-PL` project, which finishes before `module-gate` starts, so
    // nothing here races that project's assertions.

    const list = await api.createShoppingList(token, { name: listName });
    listId = list.id;
    await api.addShoppingListItem(token, listId, {
      name: "E2E-Pozycja",
      quantity: 2,
      unit: "pcs",
    });

    // globalSetup seeds a location, so the document always has one.
    const storageId = (await api.listStorages(token))[0].id;
    const document = await api.createDocument(token, {
      type: "INT",
      source_location_id: storageId,
      target_location_id: storageId,
      lines: [{ name: "E2E-Pozycja-Dokumentu", expected_quantity: 4 }],
    });
    documentId = document.id;
  });

  test.afterAll(async () => {
    if (token && listId) {
      await api.deleteShoppingList(token, listId).catch(() => {});
    }
    if (token && documentId) {
      await api.cancelDocument(token, documentId).catch(() => {});
      await api.deleteDocument(token, documentId).catch(() => {});
    }
  });

  test("signs in through the Polish login form", async ({ page }) => {
    // No polishPage fixture here: this is the unauthenticated screen, and it
    // takes its language from the browser locale the project sets.
    await page.goto("/login");

    // Typed selectors rather than labels: the labels are the translations
    // this project exists to exercise, and a password input has no ARIA role.
    const email = page.locator('input[type="email"]');
    await expect(email).toBeVisible({ timeout: 15000 });
    await expectNoRawI18nKeys(page);

    await email.fill(ADMIN_EMAIL);
    await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
    await page.locator('button[type="submit"]').click();

    // Landing route depends on the active profile, so assert only that the
    // login screen is behind us.
    await page.waitForURL((url) => !url.pathname.startsWith("/login"), {
      timeout: 20000,
    });
    await expect(page.locator('input[type="password"]')).toHaveCount(0);
    await expectNoRawI18nKeys(page);
  });

  test("lists documents", async ({ page, polishPage }) => {
    const loaded = expectApiOk(page, "/api/v1/warehouse/documents");
    await page.goto("/warehouse");
    await loaded;

    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({
      timeout: 15000,
    });
    await expectNoRawI18nKeys(page);
  });

  test("opens a document detail", async ({ page, polishPage }) => {
    const loaded = expectApiOk(
      page,
      new RegExp(`/api/v1/warehouse/documents/${documentId}(\\?|$)`),
    );
    await page.goto(`/warehouse/documents/${documentId}`);
    await loaded;

    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({
      timeout: 15000,
    });
    await expectNoRawI18nKeys(page);
  });

  test("opens a shopping list and its detail", async ({ page, polishPage }) => {
    const loaded = expectApiOk(page, "/api/v1/shopping-lists");
    await page.goto("/shopping-lists");
    await loaded;

    await expect(page.getByText(listName).first()).toBeVisible({
      timeout: 15000,
    });
    await expectNoRawI18nKeys(page);

    const detailLoaded = expectApiOk(
      page,
      `/api/v1/shopping-lists/${listId}`,
    );
    await page.goto(`/shopping-lists/${listId}`);
    await detailLoaded;

    await expect(page.getByText("E2E-Pozycja").first()).toBeVisible({
      timeout: 15000,
    });
    await expectNoRawI18nKeys(page);
  });
});
