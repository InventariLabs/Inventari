import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";
import { pickLocationSettingsPlace } from "./helpers/location-settings";

/**
 * Printing a shelf's label is daily work — a new shelf, a torn sticker — so
 * it has to be on the surface of Warehouse: a menu entry that lists the
 * shelves with their codes and prints their labels, and the sheet a scanned
 * shelf opens offering the same label. Neither goes through Configuration.
 */

const UID = Date.now().toString(36);

test.describe("Warehouse — shelf labels on the surface", () => {
  let warehouseName: string;
  let shelfName: string;
  let shelfCode: string;

  test.beforeAll(async ({ playwright, baseURL }, testInfo) => {
    const ctx = await playwright.request.newContext({ baseURL });
    const api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    const token = auth.access_token;
    await api.enableAllModules(token);

    // Two workers can read one millisecond for UID, and two concurrent
    // creates of one location name both succeed, so the worker index keeps
    // each worker on its own warehouse.
    warehouseName = `E2E-Labels-WH-${UID}-w${testInfo.workerIndex}`;
    shelfName = `E2E-Labels-Shelf-${UID}-w${testInfo.workerIndex}`;
    const warehouse = await api.createStorageIdempotent(token, {
      name: warehouseName,
    });
    const shelf = (await api.createStorageIdempotent(token, {
      name: shelfName,
      parent_id: warehouse.id,
    })) as { id: string; short_code?: string };
    const read = await ctx.get(`/api/v1/locations/${shelf.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    shelfCode = (await read.json()).short_code;
  });

  test("the Warehouse menu lists the shelves with their codes and prints their labels", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/warehouse/todo");

    // Step 1: the entry in the module bar — no visit to Configuration.
    await page
      .getByRole("navigation", { name: "Module navigation" })
      .getByRole("link", { name: "Codes and labels" })
      .click();
    await expect(
      page.getByRole("heading", { name: "Codes and labels", level: 1 }),
    ).toBeVisible();

    // A test database holds many warehouses; a person with one lands on it.
    await pickLocationSettingsPlace(page, warehouseName);
    await expect(
      page
        .getByRole("row")
        .filter({ hasText: shelfName })
        .getByText(shelfCode, { exact: true }),
    ).toBeVisible();

    // Step 2: print.
    await page
      .getByRole("button", { name: "Print labels for this list" })
      .click();
    const sheet = page.getByRole("dialog", { name: "Location labels" });
    await expect(sheet).toBeVisible();
    await expect(
      sheet.getByRole("button", { name: /^Download \d+ labels?$/ }),
    ).toBeEnabled({ timeout: 15000 });
  });

  test("on a phone the module menu reaches the same list", async ({
    page,
    authenticatedPage,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/warehouse/todo");

    // A document reload racing the first tap starts the menu closed again, and
    // it can land at any point of the sequence below. So the whole sequence is
    // retried from a settled page, not just the tap: open the menu when it is
    // closed, follow the link, and wait for the screen it leads to.
    const more = page.getByRole("button", { name: "More" });
    const heading = page.getByRole("heading", {
      name: "Codes and labels",
      level: 1,
    });
    await expect(async () => {
      if (
        (await more.getAttribute("aria-expanded", { timeout: 2000 })) !== "true"
      ) {
        await more.click({ timeout: 2000 });
      }
      await page
        .getByRole("link", { name: "Codes and labels" })
        .click({ timeout: 2000 });
      await expect(heading).toBeVisible({ timeout: 2000 });
    }).toPass({ timeout: 20000 });
    await expect(
      page.getByRole("button", { name: "Print labels for this list" }),
    ).toBeVisible();
  });

  test("a scanned shelf offers its own label", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/warehouse/scan");

    await page
      .getByPlaceholder("Document number or scanned code…")
      .fill(shelfCode);
    await page.keyboard.press("Enter");

    const contents = page.getByRole("dialog", { name: new RegExp(shelfName) });
    await expect(contents).toBeVisible({ timeout: 15000 });
    await contents.getByRole("button", { name: "Print label" }).click();

    const sheet = page.getByRole("dialog", { name: "Location labels" });
    await expect(sheet).toBeVisible();
    await expect(
      sheet.getByRole("button", { name: "Download 1 label" }),
    ).toBeEnabled({ timeout: 15000 });
  });
});
