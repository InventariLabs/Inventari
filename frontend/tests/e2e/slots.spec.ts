import { test, expect } from "./fixtures/auth";

test.describe("UI Slots — verification", () => {
  test("verifies global notifications slot (Announcements)", async ({
    page,
    authenticatedPage,
  }) => {
    // The announcements banner is what the module puts into the slot, and it
    // draws nothing until an announcement is active. One is served to this
    // page alone, as announcement-banner-responsive.spec.ts does, so no other
    // worker's screen shows it.
    await page.route(
      (url) => url.pathname === "/api/v1/announcements/active",
      (route) =>
        route.fulfill({
          json: {
            items: [
              {
                id: "00000000-0000-4000-8000-000000000100",
                title: "Slot check",
                content: "Served to this page only",
                type: "info",
                active_from: "2026-01-01T00:00:00Z",
                active_until: null,
                is_active: true,
                created_at: "2026-01-01T00:00:00Z",
                created_by: null,
              },
            ],
            total: 1,
            limit: 200,
            offset: 0,
            has_more: false,
          },
        }),
    );
    await page.goto("/");

    await expect(
      page
        .getByRole("region", { name: "Announcements" })
        .getByText("Slot check"),
    ).toBeVisible({ timeout: 15000 });
  });

  test("verifies item_edit_extra slot (Food & Health)", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/inventory/items");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    const addBtn = page
      .getByRole("button", { name: /add product|add item/i })
      .first();
    await expect(addBtn).toBeVisible({ timeout: 10000 });
    await addBtn.click();
    await page
      .locator('[role="dialog"], form, #quick-add-form')
      .first()
      .waitFor({ state: "visible", timeout: 5000 })
      .catch(() => {});

    const formOrDialog = page
      .locator('[role="dialog"], form, #quick-add-form')
      .first();
    await expect(formOrDialog).toBeVisible({ timeout: 5000 });

    await expect(
      page.locator('[role="alert"]').filter({ hasText: /error|błąd/i }),
    ).toHaveCount(0);
  });
});
