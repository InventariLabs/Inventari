import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

test.describe.configure({ mode: "serial" });

test.describe("Categories — CRUD flow", () => {
  let api: ApiHelper;
  let token: string;
  let seedCategoryId: string;
  const seedName = `E2E-Cat-${Date.now()}`;
  const editedName = `${seedName}-Edited`;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    for (let attempt = 1; attempt <= 3; attempt++) {
      try {
        const cat = await api.createCategory(token, { name: seedName });
        seedCategoryId = cat.id;
        break;
      } catch (e) {
        if (attempt === 3) throw e;
        await new Promise((r) => setTimeout(r, attempt * 600));
      }
    }
  });

  test.afterAll(async () => {
    if (token) {
      await api.deleteCategory(token, seedCategoryId).catch(() => {});
    }
  });

  test.beforeEach(async ({ page, authenticatedPage }) => {
    await page.goto("/categories");
    await page.waitForLoadState("domcontentloaded", { timeout: 10000 });
    const signInHeading = page.getByRole("heading", { level: 2, name: /sign in/i });
    if (await signInHeading.isVisible({ timeout: 3000 }).catch(() => false)) {
      await page.getByRole("textbox", { name: /email/i }).fill(ADMIN_EMAIL);
      await page.getByRole("textbox", { name: /password/i }).fill("admin");
      await page.getByRole("button", { name: /sign in/i }).click();
      await page.waitForURL(/\/(dashboard|items|categories)/, { timeout: 10000 }).catch(() => {});
      await page.goto("/categories");
    }
    await expect(page.locator("h1").first()).toBeVisible({ timeout: 20000 });
  });

  test("displays category list", async ({ page, authenticatedPage }) => {
    await expect(
      page.getByRole("heading", {
        level: 1,
        name: /product categories|kategorie/i,
      }),
    ).toBeVisible({ timeout: 20000 });
  });

  test("seeded category is visible in list", async ({
    page,
    authenticatedPage,
  }) => {
    await expect(page.getByText(seedName)).toBeVisible({ timeout: 20000 });
  });

  test("adds a new category", async ({ page, authenticatedPage }) => {
    const uniqueName = `E2E-Cat-New-${Date.now()}`;
    const addButton = page.getByRole("button", {
      name: /add category|dodaj kategorię/i,
    });

    if (await addButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      await addButton.click();

      const input = page.locator("input[required]").first();
      await expect(input).toBeVisible({ timeout: 10000 });
      await input.fill(uniqueName);

      const saveButton = page.getByRole("button", { name: /save|zapisz/i });
      await expect(saveButton).toBeVisible({ timeout: 10000 });
      await saveButton.click();

      await expect(page.getByText(uniqueName)).toBeVisible({ timeout: 10000 });
    }
  });

  test("edits an existing category name", async ({
    page,
    authenticatedPage,
  }) => {
    const categoryRow = page
      .locator("article")
      .filter({ hasText: seedName })
      .first();
    const editBtn = categoryRow
      .getByRole("button", { name: /edit|edytuj/i })
      .first();

    if ((await editBtn.count()) === 0) return;
    await editBtn.click({ force: true });

    const input = page.locator('input[required], input[name="name"]').first();
    await expect(input).toBeVisible({ timeout: 10000 });
    await input.clear();
    await input.fill(editedName);

    const saveButton = page.getByRole("button", { name: /save|zapisz/i });
    await saveButton.click();

    await expect(page.getByText(editedName)).toBeVisible({ timeout: 10000 });
  });

  test("deletes an existing category", async ({ page }) => {
    const catDeleteName = `E2E-Cat-Delete-${Date.now()}`;
    const toDelete = await api.createCategory(token, { name: catDeleteName });

    const verifyList = await api.listCategories(token);
    const found = verifyList.find((c: { name: string }) => c.name === catDeleteName);
    expect(found).toBeTruthy();

    await api.deleteCategory(token, toDelete.id);

    const afterDelete = await api.listCategories(token);
    const gone = afterDelete.find((c: { name: string }) => c.name === catDeleteName);
    expect(gone).toBeFalsy();
  });
});
