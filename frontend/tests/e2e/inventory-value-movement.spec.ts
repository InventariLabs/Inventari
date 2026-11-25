import { type Page } from "@playwright/test";
import { test, expect } from "./fixtures/auth";
import { startSeed, type ReceivingSeed } from "./helpers/receive-seed";
import { setValuation, type Valuation } from "./helpers/valuation";
import { pickDay } from "./helpers/date-picker";

/**
 * The value-movement statement: what the stock was worth when a period
 * opened, what moved it, and what it was worth when it closed — reached from
 * Stock on a date by the button that carries the day across.
 *
 * Each figure has a component test and the API has its own; this walks the
 * wiring between them — a link that drops or mangles the day, a period the
 * server is asked for that is not the one on the screen, a file that is not
 * the statement. Tracking value is a setting of the whole organisation, so
 * the spec runs in the one-worker `value-tracking` project and puts it back.
 *
 * The ledger of a stack starts on the day its first movement was posted, so
 * a day inside the ledger but outside the current month can only lie ahead:
 * the days walked here are in next month.
 */

let before: Valuation | undefined;

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
async function stockWorthSomething(seed: ReceivingSeed) {
  const shelf = await seed.shelf("Shelf");
  const supplier = await seed.partner("Supplier", "SUPPLIER");
  const milk = await seed.product("Milk");
  const receipt = await seed.api.createDocument(seed.token, {
    type: "IN",
    partner_id: supplier.id,
    target_location_id: shelf.id,
    lines: [
      {
        product_template_id: milk.id,
        expected_quantity: 10,
        unit_price: "12.50",
      },
    ],
  });
  await seed.api.confirmDocument(seed.token, receipt.id);
  await seed.api.completeDocument(seed.token, receipt.id);
}

/** The 15th of next month, as the date fields write it. */
function midNextMonth(): { day: string; first: string } {
  const now = new Date();
  const month = new Date(now.getFullYear(), now.getMonth() + 1, 1);
  const iso = (d: number) =>
    [
      month.getFullYear(),
      String(month.getMonth() + 1).padStart(2, "0"),
      String(d).padStart(2, "0"),
    ].join("-");
  return { day: iso(15), first: iso(1) };
}

/** The number a money cell prints: "$1,250.00" is 1250, "-$5.00" is -5. */
function figure(text: string): number {
  return Number(text.replace(/[^0-9.-]/g, ""));
}

/** The value cell of the statement's row, by what the row says. */
async function statementFigure(page: Page, row: RegExp): Promise<number> {
  const line = page.getByRole("row").filter({ hasText: row });
  return figure(await line.getByRole("cell").last().innerText());
}

test("the button on Stock on a date opens the statement of that day's month, which adds up to the same stock", async ({
  page,
  playwright,
  baseURL,
  authenticatedPage: _auth,
}, testInfo) => {
  const seed = await startSeed({ playwright }, baseURL, testInfo);
  await stockWorthSomething(seed);
  const { day, first } = midNextMonth();

  await page.goto(`/inventory/stock/as-of?date=${day}`);
  const asOfTotal = figure(
    await page
      .getByRole("row")
      .filter({ hasText: /^Total/ })
      .getByRole("cell")
      .last()
      .innerText(),
  );
  expect(asOfTotal).toBeGreaterThanOrEqual(125);

  const answered = page.waitForResponse(
    (response) =>
      response.url().includes("/api/v1/stock-value-movement?") &&
      response.request().method() === "GET",
  );
  await page.getByRole("button", { name: "Value movement" }).click();
  await expect(page).toHaveURL(new RegExp(`/value-movement\\?to=${day}$`));

  // The period the server was asked for is the month the day is in, not the
  // current one, and it answered with a statement.
  const response = await answered;
  expect(response.status()).toBe(200);
  const body = await response.json();
  expect(body.date_from).toBe(first);
  expect(body.date_to).toBe(day);
  await expect(page.getByText(/ends before it starts/)).toHaveCount(0);

  // The three figures the statement is for, and the lines between them.
  const opening = await statementFigure(page, /^Value on .*start of the day/);
  const closing = await statementFigure(page, /^Value on .*end of the day/);
  expect(closing).toBe(asOfTotal);
  expect(opening).toBe(asOfTotal);
  let lines = 0;
  for (const label of [
    /^Receipts/,
    /^Used/,
    /^Disposed of/,
    /^Produced and returned/,
    /^Dispatched/,
    /^Other issues/,
    /^Change in production/,
    /^Other changes/,
  ]) {
    const row = page.getByRole("row").filter({ hasText: label });
    if ((await row.count()) > 0) {
      lines += figure(await row.getByRole("cell").last().innerText());
    }
  }
  expect(Math.round((opening + lines) * 100)).toBe(Math.round(closing * 100));
});

test("a day before the ledger begins is answered with where it begins, not with a reversed period", async ({
  page,
  authenticatedPage: _auth,
}) => {
  await page.goto("/inventory/stock/as-of?date=2001-03-15");
  await page.getByRole("button", { name: "Value movement" }).click();
  await expect(page).toHaveURL(/\/value-movement\?to=2001-03-15$/);

  await expect(
    page.getByText(/The movement ledger starts on .*first one can start on/),
  ).toBeVisible({ timeout: 15000 });
  await expect(page.getByText(/ends before it starts/)).toHaveCount(0);
  // Nothing to export from a refusal.
  await expect(page.getByRole("button", { name: "Export" })).toBeDisabled();
});

test("a period set by hand is asked for as set, and its file is the statement", async ({
  page,
  playwright,
  baseURL,
  authenticatedPage: _auth,
}, testInfo) => {
  const seed = await startSeed({ playwright }, baseURL, testInfo);
  await stockWorthSomething(seed);
  const { day, first } = midNextMonth();
  const from = first.replace(/-01$/, "-05");

  await page.goto(`/inventory/stock/value-movement?to=${day}`);
  await expect(
    page.getByRole("row").filter({ hasText: /^Value on .*start of the day/ }),
  ).toBeVisible({ timeout: 15000 });

  const asked = page.waitForRequest(
    (request) =>
      request.url().includes("/api/v1/stock-value-movement?") &&
      request.url().includes(`date_from=${from}`),
  );
  await pickDay(page, page.getByRole("combobox", { name: "From" }), from);
  const request = await asked;
  expect(request.url()).toContain(`date_to=${day}`);
  await expect(page).toHaveURL(new RegExp(`from=${from}`));
  await expect(
    page
      .getByRole("table")
      .getByRole("row")
      .filter({ hasText: /^Value on .*start of the day/ }),
  ).toBeVisible();

  const downloading = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export" }).click();
  const file = await downloading;
  expect(file.suggestedFilename()).toBe(`value_movement_${from}_${day}.xlsx`);
  const path = await file.path();
  const { readFile } = await import("node:fs/promises");
  const bytes = await readFile(path);
  // A spreadsheet is a zip archive.
  expect(bytes.subarray(0, 2).toString()).toBe("PK");
  expect(bytes.length).toBeGreaterThan(1000);
});
