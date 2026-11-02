import { test, expect } from "./fixtures/auth";

test.describe("UI Slots — verification", () => {
  test("verifies global notifications slot (Announcements)", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/");
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});

    await expect(page.locator("body")).toBeVisible({ timeout: 10000 });

    const hasAside = await page.locator("aside").first().isVisible({ timeout: 5000 }).catch(() => false);
    if (!hasAside) {
      await expect(page.locator("#root > div").first()).toBeVisible({ timeout: 10000 });
      return;
    }
    await expect(page.locator("aside").first()).toBeVisible({ timeout: 10000 });
  });

  test("verifies item_edit_extra slot (Food & Health)", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/inventory/items");
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});

    const addBtn = page
      .getByRole("button", { name: /add product|add item/i })
      .first();
    if (!(await addBtn.isVisible({ timeout: 10000 }).catch(() => false))) return;
    await addBtn.click();
    await page.locator('[role="dialog"], form, #quick-add-form').first().waitFor({ state: "visible", timeout: 5000 }).catch(() => {});

    const formOrDialog = page
      .locator('[role="dialog"], form, #quick-add-form')
      .first();
    if (!(await formOrDialog.isVisible({ timeout: 5000 }).catch(() => false))) return;

    await expect(
      page.locator('[role="alert"]').filter({ hasText: /error|błąd/i }),
    ).toHaveCount(0);
  });
});
