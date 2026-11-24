import { type Page } from "@playwright/test";
import { test, expect } from "./fixtures/auth";
import { startSeed, type ReceivingSeed } from "./helpers/receive-seed";

/**
 * The outbound hand-offs the documentation walks: a completed dispatch keeps
 * its packages as a read-only record, and a picking session over one document
 * started from a list ends on that document's page, where Pack lands on the
 * Pack step and Complete and book completes the dispatch.
 *
 * Both halves have unit tests of their own; this walks the wiring between the
 * list, the picking sheet and the document page, and reads each result back
 * through the API.
 */

interface Dispatch {
  id: string;
  number: string;
  product: string;
  shelfId: string;
}

/** A confirmed dispatch of one product, five of it on a shelf, two ordered. */
async function dispatchOfOne(seed: ReceivingSeed): Promise<Dispatch> {
  const shelf = await seed.shelf("Shelf");
  const customer = await seed.partner("Customer", "CUSTOMER");
  const product = await seed.product("Cheese");
  const item = await seed.api.createItemForTemplate(seed.token, {
    name: product.name,
    template_id: product.id,
    location_id: shelf.id,
    quantity: 5,
  });
  const doc = await seed.api.createDocument(seed.token, {
    type: "OUT",
    partner_id: customer.id,
    source_location_id: shelf.id,
    lines: [
      {
        item_id: item.id,
        product_template_id: product.id,
        expected_quantity: 2,
      },
    ],
  });
  await seed.api.confirmDocument(seed.token, doc.id);
  const read = await seed.api.getDocument(seed.token, doc.id);
  return {
    id: doc.id,
    number: read.number as string,
    product: product.name,
    shelfId: shelf.id,
  };
}

/** Picks the dispatch's one line in full on the sheet that is open. */
async function pickTheLine(page: Page, seed: ReceivingSeed, d: Dispatch) {
  const sheet = page.getByRole("dialog", { name: "Picking" });
  await expect(sheet).toBeVisible({ timeout: 15000 });
  // Where the organisation asks for the shelf to be confirmed by scan, the
  // picker scans it first.
  const shelfPrompt = sheet.getByText("Scan the location label").first();
  if (await shelfPrompt.isVisible()) {
    const shelf = await seed.request.get(`/api/v1/locations/${d.shelfId}`, {
      headers: { Authorization: `Bearer ${seed.token}` },
    });
    await sheet
      .getByRole("textbox", { name: "Scan barcode or type…" })
      .fill((await shelf.json()).short_code);
    await sheet.getByRole("button", { name: "Scan", exact: true }).click();
    await expect(shelfPrompt).toBeHidden();
  }
  await sheet.getByRole("button", { name: "Pick full amount" }).click();
  const summary = page.getByRole("dialog", { name: "Picking complete" });
  await expect(summary).toBeVisible({ timeout: 15000 });
  await expect(summary).toContainText("1 of 1 lines picked");
  return summary;
}

/** The list, narrowed to the dispatch, with its row ticked and Pick pressed. */
async function startFromTheList(page: Page, d: Dispatch) {
  await page.goto(`/warehouse/all?search=${encodeURIComponent(d.number)}`);
  await page.getByRole("checkbox", { name: `Select ${d.number}` }).check();
  await page.getByRole("button", { name: "Pick 1 selected" }).click();
}

const status = async (seed: ReceivingSeed, d: Dispatch) =>
  (await seed.api.getDocument(seed.token, d.id)).status;

test.describe("a picking session over one document, started from the list", () => {
  test("Complete and book leaves the list for the document, which completes there", async ({
    page,
    playwright,
    baseURL,
    authenticatedPage: _auth,
  }, testInfo) => {
    const seed = await startSeed({ playwright }, baseURL, testInfo);
    const d = await dispatchOfOne(seed);

    await startFromTheList(page, d);
    const summary = await pickTheLine(page, seed, d);
    await summary
      .getByRole("button", { name: "Complete and book", exact: true })
      .click();

    await expect(page).toHaveURL(new RegExp(`/warehouse/documents/${d.id}$`));
    await expect
      .poll(() => status(seed, d), { timeout: 15000 })
      .toBe("COMPLETED");
    // The hand-off is spent: the page does not complete it a second time.
    await page.reload();
    await expect(page).toHaveURL(new RegExp(`/warehouse/documents/${d.id}$`));
    expect(await status(seed, d)).toBe("COMPLETED");
  });

  test("Pack leaves the list for the document's Pack step, the dispatch still open", async ({
    page,
    playwright,
    baseURL,
    authenticatedPage: _auth,
  }, testInfo) => {
    const seed = await startSeed({ playwright }, baseURL, testInfo);
    const d = await dispatchOfOne(seed);

    await startFromTheList(page, d);
    const summary = await pickTheLine(page, seed, d);
    await summary.getByRole("button", { name: "Pack", exact: true }).click();

    await expect(page).toHaveURL(
      new RegExp(`/warehouse/documents/${d.id}#pack$`),
    );
    const card = page
      .getByRole("heading", { name: "Packing", exact: true })
      .locator("xpath=ancestor::*[contains(@class,'p-4')][1]");
    await expect(
      card.getByRole("button", { name: "Everything in one package" }),
    ).toBeVisible({ timeout: 15000 });
    expect(await status(seed, d)).toBe("CONFIRMED");
    // An open dispatch is a task on Start for every spec that runs after.
    await seed.api.cancelDocument(seed.token, d.id).catch(() => {});
    await seed.api.deleteDocument(seed.token, d.id).catch(() => {});
  });
});

test.describe("a completed dispatch's packing", () => {
  test("keeps its packages as a read-only card with each one's slip and label", async ({
    page,
    playwright,
    baseURL,
    authenticatedPage: _auth,
  }, testInfo) => {
    const seed = await startSeed({ playwright }, baseURL, testInfo);
    const d = await dispatchOfOne(seed);

    await page.goto(`/warehouse/documents/${d.id}`);
    await page.getByRole("button", { name: "Scan picking" }).click();
    const summary = await pickTheLine(page, seed, d);
    await summary.getByRole("button", { name: "Pack", exact: true }).click();

    const card = page
      .getByRole("heading", { name: "Packing", exact: true })
      .locator("xpath=ancestor::*[contains(@class,'p-4')][1]");
    await card.getByRole("button", { name: "Everything in one package" }).click();
    await expect(card.getByRole("list", { name: "Packages" })).toBeVisible();
    await card.getByRole("button", { name: "Complete dispatch" }).click();
    await expect
      .poll(() => status(seed, d), { timeout: 15000 })
      .toBe("COMPLETED");

    // The packages stay, as what was shipped: a slip and a label for each,
    // and nothing left to change.
    await page.reload();
    const record = page
      .getByRole("heading", { name: "Packing", exact: true })
      .locator("xpath=ancestor::*[contains(@class,'p-4')][1]");
    await expect(record).toBeVisible({ timeout: 15000 });
    await expect(
      record.getByText(/^What was shipped, package by package/),
    ).toBeVisible();
    const packages = record.getByRole("list", { name: "Packages" });
    await expect(
      packages.getByRole("button", { name: "Packing slip" }),
    ).toHaveCount(1);
    await expect(packages.getByRole("button", { name: "Label" })).toHaveCount(1);
    await expect(
      record.getByRole("button", { name: "Add package" }),
    ).toHaveCount(0);
    await expect(
      record.getByRole("button", { name: "Complete dispatch" }),
    ).toHaveCount(0);
    await expect(
      record.getByRole("button", { name: "Remove package" }),
    ).toHaveCount(0);

    // The slip is a PDF of the shipped package.
    const pending = page.waitForEvent("download");
    await packages.getByRole("button", { name: "Packing slip" }).click();
    expect((await pending).suggestedFilename()).toMatch(/^packing_slip_.+\.pdf$/);
  });

  test("shows no packing card when it shipped without packages", async ({
    page,
    playwright,
    baseURL,
    authenticatedPage: _auth,
  }, testInfo) => {
    const seed = await startSeed({ playwright }, baseURL, testInfo);
    const d = await dispatchOfOne(seed);

    await page.goto(`/warehouse/documents/${d.id}`);
    await page.getByRole("button", { name: "Scan picking" }).click();
    const summary = await pickTheLine(page, seed, d);
    await summary
      .getByRole("button", { name: "Complete and book", exact: true })
      .click();
    await expect
      .poll(() => status(seed, d), { timeout: 15000 })
      .toBe("COMPLETED");

    await page.reload();
    await expect(
      page.getByRole("heading", { name: d.number }).or(page.getByText(d.number).first()),
    ).toBeVisible({ timeout: 15000 });
    await expect(
      page.getByRole("heading", { name: "Packing", exact: true }),
    ).toHaveCount(0);
  });
});
