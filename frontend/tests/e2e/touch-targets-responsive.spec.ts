import { type Locator } from "@playwright/test";
import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

async function target(locator: Locator) {
  await expect(locator).toBeVisible({ timeout: 15000 });
  const box = await locator.boundingBox();
  expect(box!.width).toBeGreaterThanOrEqual(24);
  expect(box!.height).toBeGreaterThanOrEqual(24);
}

test.beforeEach(async ({ page, authenticatedPage }) => {
  void authenticatedPage;
  await page.setViewportSize({ width: 360, height: 800 });
});

test("location selection fills the row without opening it", async ({
  page,
  request,
}, testInfo) => {
  const api = new ApiHelper(request);
  const token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
  const parent = await api.createStorage(token, {
    name: `Touch parent ${Date.now()}-w${testInfo.workerIndex}`,
  });
  let childId = "";
  try {
    const child = await api.createStorage(token, {
      name: "Touch child",
      parent_id: parent.id,
    });
    childId = child.id;
    await page.goto(`/inventory/locations/${parent.id}`);
    const checkbox = page.getByRole("checkbox", { name: "Select Touch child" });
    const label = page.locator("label").filter({ has: checkbox });
    await target(label);
    const row = label.locator("..");
    expect((await label.boundingBox())!.height).toBeCloseTo(
      (await row.boundingBox())!.height,
      0,
    );
    await label.click({ position: { x: 5, y: 5 } });
    await expect(checkbox).toBeChecked();
    await expect(page).toHaveURL(new RegExp(`/inventory/locations/${parent.id}`));
  } finally {
    if (childId) await api.deleteStorage(token, childId);
    await api.deleteStorage(token, parent.id);
  }
});

test("product form and location breadcrumb links have a phone target", async ({
  page,
  request,
}, testInfo) => {
  const api = new ApiHelper(request);
  const token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
  const location = await api.createStorage(token, {
    name: `Touch breadcrumb ${Date.now()}-w${testInfo.workerIndex}`,
  });
  try {
    await page.goto("/inventory/items/add");
    await target(page.getByRole("link", { name: "Manage locations" }));
    await page.goto(`/inventory/locations/${location.id}`);
    await target(
      page
        .getByRole("navigation", { name: "Location path" })
        .getByRole("button", { name: "All locations", exact: true }),
    );
  } finally {
    await api.deleteStorage(token, location.id);
  }
});

test("overview shopping list name has a phone target", async ({ page }) => {
  const list = { id: "touch-list", name: "Touch shopping list", items: [] };
  await page.route("**/api/v1/shopping-lists**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    await route.fulfill({
      json: path.endsWith("/touch-list")
        ? list
        : { items: [list], total: 1, page: 1, size: 100, pages: 1 },
    });
  });
  await page.goto("/inventory");
  await target(page.getByRole("link", { name: list.name }));
});

test("analytics product links have a phone target", async ({ page }) => {
  await page.route("**/api/v1/stats/config", (route) =>
    route.fulfill({
      json: { enable_analytics: true, show_inventory_value: true },
    }),
  );
  await page.route("**/api/v1/stats/smart-alerts", (route) =>
    route.fulfill({
      json: {
        total_alerts: 1,
        alerts: [
          {
            type: "LOW_STOCK",
            severity: "low",
            item_name: "Touch product",
            action: "view_item",
            action_param: "touch-product",
          },
        ],
      },
    }),
  );
  await page.goto("/inventory/stats/analytics");
  await target(page.getByRole("link", { name: "Touch product" }));
});
