import { copyFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";
import type { Locator, Page } from "@playwright/test";
import { test, expect } from "./fixtures/auth";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";
import { ApiHelper } from "./helpers/api";
import { expectApiOk } from "./helpers/page-load";

/** Written by `fixtures/make_grocy_db.py` from Grocy's own schema. */
const GROCY_DB = fileURLToPath(
  new URL("./fixtures/grocy.db", import.meta.url),
);

/**
 * A copy of the fixture that is a household of its own: a move recognises what
 * an earlier one brought by Grocy's ids, and reuses places, groups, stores and
 * products by name, so every run gets new ids and new names.
 */
function ownHousehold(path: string, tag: string, idsFrom: number): void {
  copyFileSync(GROCY_DB, path);
  const db = new DatabaseSync(path);
  for (const table of [
    "locations",
    "product_groups",
    "shopping_locations",
    "products",
  ])
    db.prepare(`UPDATE ${table} SET name = name || ' ' || ?`).run(tag);
  db.prepare("UPDATE products SET id = id + ?").run(idsFrom);
  db.prepare(
    "UPDATE product_barcodes SET product_id = product_id + ?, barcode = barcode || ?",
  ).run(idsFrom, tag);
  db.prepare(
    "UPDATE stock SET product_id = product_id + ?, stock_id = stock_id || ?",
  ).run(idsFrom, tag);
  db.close();
}

async function readFile(page: Page, path: string): Promise<Locator> {
  await page.getByRole("button", { name: "Import", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Import products" });
  const chooser = page.waitForEvent("filechooser");
  await dialog.getByRole("button", { name: /Import from Grocy/ }).click();
  const analyzed = expectApiOk(page, "/api/v1/items/import/grocy/analyze", {
    method: "POST",
  });
  await (await chooser).setFiles(path);
  await analyzed;
  return dialog;
}

async function move(page: Page, dialog: Locator): Promise<void> {
  const moved = expectApiOk(page, /\/api\/v1\/items\/import\/grocy$/, {
    method: "POST",
  });
  await dialog.getByRole("button", { name: "Move in" }).click();
  await moved;
  await expect(dialog.getByText("Import complete")).toBeVisible();
}

/** The number the review shows for one kind of record in the file. */
function count(dialog: Locator, label: string): Locator {
  return dialog
    .locator("dl > div")
    .filter({ has: dialog.page().getByText(label, { exact: true }) })
    .locator("dd");
}

/** The line of "Stays in Grocy" for one kind of record, with its count. */
function stays(dialog: Locator, label: string): Locator {
  return dialog.getByRole("listitem").filter({ hasText: label });
}

test.describe("Moving in from Grocy", () => {
  const tag = Math.random().toString(36).substring(2, 8);
  const named = (name: string) => `E2E-Grocy ${name} ${tag}`;
  let api: ApiHelper;
  let token: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    api = new ApiHelper(await playwright.request.newContext({ baseURL }));
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
  });

  // The records only: the locations, category and supplier carry the E2E-
  // prefix the next run's global setup clears.
  test.afterAll(async () => {
    for (const item of await api.listItems(token, `search=${tag}&limit=50`))
      await api.deleteItem(token, item.id);
  });

  test("reads the file, moves it, and adds nothing the second time", async ({
    page,
    authenticatedPage,
  }, testInfo) => {
    const file = testInfo.outputPath("grocy.db");
    ownHousehold(file, tag, Math.floor(Math.random() * 1_000_000_000));
    await page.goto("/inventory/items");

    let dialog = await readFile(page, file);

    await expect(count(dialog, "Products")).toHaveText("3");
    await expect(count(dialog, "Batches of stock")).toHaveText("3");
    await expect(count(dialog, "Locations")).toHaveText("2");
    await expect(count(dialog, "Product groups")).toHaveText("1");
    await expect(count(dialog, "Stores")).toHaveText("1");
    for (const [label, left] of [
      ["Products switched off in Grocy", 1],
      ["Locations switched off in Grocy", 1],
      ["Product groups switched off in Grocy", 1],
      ["Stores switched off in Grocy", 1],
      ["Extra barcodes (a product here keeps one)", 1],
      ["Recipes", 1],
      ["Chores", 1],
    ] as const)
      await expect(stays(dialog, label)).toHaveText(`${label}${left}`);

    await move(page, dialog);

    for (const heading of [
      "2 locations created",
      "1 category created",
      "1 supplier created",
    ])
      await expect(dialog.getByText(heading)).toBeVisible();
    for (const name of ["pantry", "freezer", "sweets", "corner shop"])
      await expect(dialog.getByText(named(name))).toBeVisible();

    await dialog
      .getByRole("button", { name: "Close and view products" })
      .click();
    await page.getByTestId("list-search-input").fill(tag);
    const rows = page.getByTestId("item-name").filter({ hasText: tag });
    // Two batches of the cookies and one of the flour.
    await expect(rows).toHaveCount(3);

    dialog = await readFile(page, file);
    await expect(
      dialog.getByText(/^3 batches came across in an earlier move/),
    ).toBeVisible();

    await move(page, dialog);

    // The three batches, and the product that has no stock.
    await expect(
      dialog.getByText(/^4 entries were already here from an earlier move/),
    ).toBeVisible();
    await expect(dialog.getByText(/created$/)).toHaveCount(0);

    const listed = expectApiOk(page, /\/api\/v1\/items(\/grouped)?\?/);
    await page.reload();
    await listed;
    await page.getByTestId("list-search-input").fill(tag);
    await expect(rows).toHaveCount(3);
    expect(await api.listItems(token, `search=${tag}&limit=50`)).toHaveLength(
      3,
    );
  });
});
