import { type Page } from "@playwright/test";
import { test, expect } from "./fixtures/auth";
import {
  startSeed,
  type ReceivingSeed,
  type SeededPartner,
  type SeededProduct,
  type SeededShelf,
} from "./helpers/receive-seed";
import {
  arrivedField,
  chooseLocation,
  choosePartner,
  scanProduct,
} from "./helpers/receive-screen";

/**
 * What the office reads off the floor's work once value is tracked: a
 * write-off says why it was made and what it cost, a receipt nobody priced is
 * announced before it is posted, and the register's totals say what they fold
 * in and what they leave out.
 *
 * Every screen here has a component test; this walks the wiring between them —
 * a reason the form never sends, a notice nobody renders — which those tests
 * cannot see. Each post is read back through the API.
 *
 * Tracking value, and showing the stock value on the statistics, are settings
 * of the whole organisation, so the spec runs in the one-worker
 * `value-tracking` project and puts both back.
 */

const PROFILE = "/api/v1/warehouse/profile";
const STATS_CONFIG = "/api/v1/stats/config";

/** The two organisation-wide switches this spec needs on. */
interface Valuation {
  tracked: boolean;
  valueShown: boolean;
}

let before: Valuation | undefined;

/** Set both switches, and return what they were. */
async function setValuation(
  seed: ReceivingSeed,
  to: Valuation,
): Promise<Valuation> {
  const headers = { Authorization: `Bearer ${seed.token}` };
  const profile = await (await seed.request.get(PROFILE, { headers })).json();
  const stats = await (
    await seed.request.get(STATS_CONFIG, { headers })
  ).json();
  const put = await seed.request.put(PROFILE, {
    headers,
    data: { value_tracking_enabled: to.tracked },
  });
  if (!put.ok()) {
    throw new Error(`Could not set value tracking: ${await put.text()}`);
  }
  await seed.api.setModuleSettings(seed.token, "stats", {
    show_inventory_value: to.valueShown,
  });
  return {
    tracked: profile.value_tracking_enabled === true,
    valueShown: stats.show_inventory_value === true,
  };
}

test.beforeAll(async ({ playwright, baseURL }, testInfo) => {
  const seed = await startSeed({ playwright }, baseURL, testInfo);
  before = await setValuation(seed, { tracked: true, valueShown: true });
});

test.afterAll(async ({ playwright, baseURL }, testInfo) => {
  if (before === undefined) return;
  const seed = await startSeed({ playwright }, baseURL, testInfo);
  await setValuation(seed, before);
});

/** Ten on the shelf, received from the supplier at 12.50 each. */
async function receivedAtAPrice(
  seed: ReceivingSeed,
  product: SeededProduct,
  shelf: SeededShelf,
  supplier: SeededPartner,
) {
  const receipt = await seed.api.createDocument(seed.token, {
    type: "IN",
    partner_id: supplier.id,
    target_location_id: shelf.id,
    lines: [
      {
        product_template_id: product.id,
        expected_quantity: 10,
        unit_price: "12.50",
      },
    ],
  });
  await seed.api.confirmDocument(seed.token, receipt.id);
  await seed.api.completeDocument(seed.token, receipt.id);
}

/** The register's month as the API counts it — what the notes must say. */
async function registerSummary(seed: ReceivingSeed) {
  const today = new Date();
  const iso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
      d.getDate(),
    ).padStart(2, "0")}`;
  const first = new Date(today.getFullYear(), today.getMonth(), 1);
  const body = await seed.api.getDocumentRegister(
    seed.token,
    `date_from=${iso(first)}&date_to=${iso(today)}`,
  );
  return body.summary as {
    scrap_documents: number;
    documents_without_value: number;
  };
}

async function openRegister(page: Page) {
  await page.goto("/warehouse/register");
  await expect(
    page.getByRole("heading", { name: "Document register" }),
  ).toBeVisible();
}

test("a write-off asks why, keeps the answer and is counted at its cost", async ({
  page,
  playwright,
  baseURL,
  authenticatedPage: _auth,
}, testInfo) => {
  const seed = await startSeed({ playwright }, baseURL, testInfo);
  const shelf = await seed.shelf("Shelf");
  const supplier = await seed.partner("Supplier", "SUPPLIER");
  const milk = await seed.product("Milk");
  await receivedAtAPrice(seed, milk, shelf, supplier);

  await page.goto("/warehouse/issue");
  await page.getByRole("radio", { name: /Damaged or expired/ }).click();
  await page.getByRole("combobox", { name: /From location/ }).click();
  await page.getByPlaceholder(/Search location/).fill(shelf.name);
  await page.getByRole("button", { name: shelf.name }).click();
  await page.getByRole("combobox", { name: /Item/ }).fill(milk.name);
  await page
    .getByRole("option", { name: new RegExp(milk.name) })
    .first()
    .click();

  // No reason, no write-off: the form says so and the shelf keeps its ten.
  const post = page.getByRole("button", { name: "Write off", exact: true });
  await post.click();
  await expect(page.getByText("Pick a reason", { exact: true })).toBeVisible();
  expect(await seed.onHand(milk, shelf)).toBe(10);

  await page.getByLabel("Reason for scrapping").selectOption("EXPIRED");
  await post.click();
  await expect(
    page.getByRole("heading", { name: "Wrote off 1 line" }),
  ).toBeVisible({ timeout: 15000 });

  const document = await seed.documentLinkedFrom(page);
  expect(document.type).toBe("SCRAP");
  expect(document.reason_code).toBe("EXPIRED");
  // One of the ten, at the price it was received at.
  expect(Number(document.total_net)).toBe(12.5);
  expect(await seed.onHand(milk, shelf)).toBe(9);

  const summary = await registerSummary(seed);
  expect(summary.scrap_documents).toBeGreaterThan(0);
  await openRegister(page);
  await expect(
    page.getByText(
      `Scrap documents in these totals: ${summary.scrap_documents},`,
    ),
  ).toBeVisible();
});

test("a receipt nobody priced is announced before the post and named in the totals after it", async ({
  page,
  playwright,
  baseURL,
  authenticatedPage: _auth,
}, testInfo) => {
  const seed = await startSeed({ playwright }, baseURL, testInfo);
  const shelf = await seed.shelf("Shelf");
  const supplier = await seed.partner("Supplier", "SUPPLIER");
  const flour = await seed.product("Flour");

  await page.goto("/warehouse/receive");
  await choosePartner(page, supplier.name);
  await chooseLocation(page, shelf.name);
  await scanProduct(page, flour.barcode, flour.name);
  await arrivedField(page, flour.name).fill("3");

  const notice = page.getByText(/^Lines without a price: 1\./);
  await expect(notice).toBeVisible();
  // A price takes the line out of the count; emptying it puts it back.
  const price = page.getByRole("textbox", { name: `Unit price: ${flour.name}` });
  await price.fill("4.20");
  await expect(notice).toHaveCount(0);
  await price.fill("");
  await expect(notice).toBeVisible();

  await page.getByRole("button", { name: "Receive into stock" }).click();
  await expect(
    page.getByRole("heading", { name: /^Received \d+ lines?$/ }),
  ).toBeVisible({ timeout: 15000 });
  const document = await seed.documentLinkedFrom(page);
  expect(document.total_net ?? null).toBeNull();
  expect(await seed.onHand(flour, shelf)).toBe(3);

  const summary = await registerSummary(seed);
  expect(summary.documents_without_value).toBeGreaterThan(0);
  await openRegister(page);
  await expect(
    page.getByText(
      `Documents posted without a price: ${summary.documents_without_value}.`,
    ),
  ).toBeVisible();

  // The flour lies on the shelf worth nothing, so the stock value is a floor.
  await page.goto("/inventory/stats");
  await expect(
    page.getByText(
      /^Receipts in stock posted without a price: \d+\. This value is a lower bound\.$/,
    ),
  ).toBeVisible();
});
