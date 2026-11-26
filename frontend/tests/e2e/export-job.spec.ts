/**
 * A long spreadsheet export is written by a background job: each screen that
 * offers the export says how far the job has got and hands over the workbook
 * when it is ready.
 *
 * Needs a backend with TESTING=true (`make test-e2e`). There the
 * `X-Test-Export-Job` header answers a sheet of any length with a job, so the
 * spec follows a real one without storing thousands of records.
 */
import { execFileSync } from "node:child_process";
import type { Page } from "@playwright/test";
import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

const tag = `exportjob-${Math.random().toString(36).slice(2, 9)}`;
const products = [`${tag} flour`, `${tag} sugar`];
const asset = `${tag} drill`;

let api: ApiHelper;
let storageId: string;
const itemIds: string[] = [];

/** The Name column of a downloaded export's first sheet, header excluded. */
function exportedNames(path: string): string[] {
  // `unzip` refuses anything that is not an archive, as a workbook is.
  const sheet = execFileSync(
    "unzip",
    ["-p", path, "xl/worksheets/sheet1.xml"],
    { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 },
  );
  const cells = [
    ...sheet.matchAll(/<c r="([A-Z]+)(\d+)"[^>]*><is><t[^>]*>([^<]*)<\/t>/g),
  ].map(([, column, row, text]) => ({ column, row, text }));
  const header = cells.find((c) => c.row === "1" && c.text === "Name");
  expect(header, "the sheet has a Name column").toBeDefined();
  return cells
    .filter((c) => c.column === header?.column && c.row !== "1")
    .map((c) => c.text);
}

/**
 * Presses an export control, sends its request down the job path and returns
 * the file the screen hands over once the job is done.
 */
async function exportOverAJob(page: Page, press: () => Promise<void>) {
  const exportUrl = /\/api\/v1\/items\/export\/xlsx(\?|$)/;
  await page.route(exportUrl, (route) =>
    route.continue({
      headers: { ...route.request().headers(), "x-test-export-job": "1" },
    }),
  );
  const answered = page.waitForResponse(exportUrl);
  const downloading = page.waitForEvent("download");

  await press();

  expect(
    (await answered).status(),
    "a job answers only on a backend with TESTING=true",
  ).toBe(202);
  await expect(
    page.getByText(
      /^Preparing the export: \d+%\. The file downloads when it is ready\.$/,
    ),
  ).toBeVisible();
  const file = await downloading;
  await expect(page.getByText("Export complete")).toBeVisible();
  return {
    filename: file.suggestedFilename(),
    names: exportedNames(await file.path()),
  };
}

test.describe("Export written by a background job", () => {
  // The job starts a process of its own, which loads the whole application.
  test.describe.configure({ timeout: 60_000 });

  test.beforeAll(async ({ playwright, baseURL }) => {
    api = new ApiHelper(await playwright.request.newContext({ baseURL }));
    const { access_token: token } = await api.login(
      ADMIN_EMAIL,
      ADMIN_PASSWORD,
    );
    storageId = (await api.createStorage(token, { name: `Z_Test ${tag}` })).id;
    const record = (name: string) => ({
      name,
      quantity: 1,
      location_id: storageId,
    });
    for (const name of products) {
      itemIds.push((await api.createItem(token, record(name))).id);
    }
    itemIds.push((await api.createEquipmentItem(token, record(asset))).id);
  });

  test.afterAll(async () => {
    const { access_token: token } = await api.login(
      ADMIN_EMAIL,
      ADMIN_PASSWORD,
    );
    for (const id of itemIds) {
      await api.removeItemForGood(token, id).catch(() => {});
    }
    if (storageId) await api.deleteStorage(token, storageId).catch(() => {});
  });

  test("the product list hands over the rows its search shows", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto(`/inventory/items?search=${tag}`);
    await expect(page.getByText(products[0]).first()).toBeVisible();

    const file = await exportOverAJob(page, () =>
      page.getByRole("button", { name: "Export", exact: true }).click(),
    );

    expect(file.filename).toMatch(/^inventory_.*\.xlsx$/);
    expect(file.names.sort()).toEqual(products);
  });

  test("the settings screen hands over every record", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/settings");

    const file = await exportOverAJob(page, () =>
      page
        .getByRole("button", { name: /Download a copy of your products/ })
        .click(),
    );

    expect(file.filename).toMatch(/^inventari_export_.*\.xlsx$/);
    expect(file.names).toEqual(expect.arrayContaining([...products, asset]));
  });

  test("the equipment list hands over the equipment alone", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/equipment/assets");

    const file = await exportOverAJob(page, () =>
      page.getByRole("button", { name: "Export", exact: true }).click(),
    );

    expect(file.filename).toMatch(/^equipment_.*\.xlsx$/);
    expect(file.names).toContain(asset);
    for (const name of products) expect(file.names).not.toContain(name);
  });
});
