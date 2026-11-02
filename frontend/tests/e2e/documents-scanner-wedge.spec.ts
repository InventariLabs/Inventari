import type { Page } from "@playwright/test";
import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * A USB or Bluetooth barcode scanner types the code as keys a few ms apart and
 * closes it with Enter. The picking screen has to take that wherever the
 * focus is, not only inside its barcode field: a picker who has just tapped a
 * line still scans.
 *
 * The scanner here is `scan`: the keys dispatched inside the page in one go,
 * a burst no machine can slow down. `keyboard.type` with a small delay sent
 * each key on a round trip from the test runner, and on a starved CI runner
 * those trips outlasted the hook's 50 ms between keys — the code read as a
 * person typing, and the line was never picked.
 */

const UID = Date.now().toString(36);
const BARCODE = `29${Date.now().toString().slice(-11)}`;

/**
 * Send each read as a wedge scanner does — its keys a moment apart, then
 * Enter — and all of them in the same burst, so a double read stays inside
 * the hook's 300 ms window however slow the round trip to the page is.
 */
function scan(page: Page, ...reads: string[]) {
  return page.evaluate((codes) => {
    const target = document.activeElement ?? document.body;
    for (const code of codes) {
      for (const key of [...code.split(""), "Enter"]) {
        target.dispatchEvent(
          new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }),
        );
      }
    }
  }, reads);
}

test.describe("Documents — a hardware scanner on the picking screen", () => {
  let api: ApiHelper;
  let token: string;
  let locationId: string;
  let itemId: string;
  let templateId: string;
  let partnerId: string;
  const productName = `E2E-Wedge-Widget-${UID}`;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
    await api.enableAllModules(token);

    const storage = await api.createStorageIdempotent(token, {
      name: `E2E-Wedge-${UID}`,
      location_type: "SHELF",
    });
    locationId = storage.id;

    // The scan matches the product's code; the item joins that product by
    // name and carries the stock the dispatch takes.
    const template = await api.createProductTemplate(token, {
      name: productName,
      barcode: BARCODE,
    });
    const item = await api.createItemForTemplate(token, {
      name: productName,
      template_id: template.id,
      location_id: locationId,
      quantity: 5,
    });
    itemId = item.id;
    templateId = template.id;

    const partner = await api.createPartner(token, {
      name: `E2E-Wedge-Customer-${UID}`,
      type: "CUSTOMER",
    });
    partnerId = partner.id;
  });

  test("a code typed as a scanner types it picks the line", async ({
    page,
    authenticatedPage,
  }) => {
    const doc = await api.createDocument(token, {
      type: "OUT",
      partner_id: partnerId,
      source_location_id: locationId,
      // A line names its product as well as the stock it takes: the scan
      // matches the product, as on a dispatch made in the form.
      lines: [
        {
          item_id: itemId,
          product_template_id: templateId,
          expected_quantity: 2,
        },
      ],
    });
    await api.confirmDocument(token, doc.id);

    // The number the draft was created under changes on confirm, so the
    // page is recognised by the action it offers, not by its heading.
    await page.goto(`/warehouse/documents/${doc.id}`);
    const startPicking = page.getByRole("button", { name: "Scan picking" });
    await expect(startPicking).toBeVisible({ timeout: 15000 });
    await startPicking.click();

    const sheet = page.getByRole("dialog", { name: "Picking" });
    await expect(
      sheet.getByText("A barcode scanner can be used on this screen"),
    ).toBeVisible();
    await expect(sheet.getByText("0/1 picked")).toBeVisible();

    // Take the focus off the barcode field: the scan must not depend on it.
    await page.evaluate(() => (document.activeElement as HTMLElement)?.blur());
    // A double read: the scanner sends the same code again at once. It is
    // one item in the picker's hand, so it is one unit.
    await scan(page, BARCODE, BARCODE);

    await expect(
      page.getByText(new RegExp(`${productName} — 1 .* picked`)),
    ).toBeVisible({ timeout: 15000 });
    await expect(sheet.getByText(`${productName} — 1/2`)).toBeVisible();
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
    await expect(sheet.getByText(`${productName} — 1/2`)).toBeVisible();
    await expect(sheet.getByPlaceholder("Scan barcode or type…")).toHaveValue(
      "",
    );
  });
});
