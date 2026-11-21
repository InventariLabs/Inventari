import { test, expect } from "./fixtures/auth";
import type { APIRequestContext } from "@playwright/test";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * Maker — the batches of a run, on screen.
 *
 * A jam is made from a syrup the kitchen made itself, in two batches. The run
 * that makes the jam is closed from the browser, taking its syrup from the
 * batch whose label was scanned, and the screens that follow are the ones this
 * spec exists for: the batch record, the batch label sheet with its copies
 * and its ingredient list, the hold and its release, a run's files, and the
 * BOM's own Label tab.
 *
 * The steps build on each other, so they run in order in one worker.
 */

// One transparent pixel: the smallest file the upload accepts as an image.
const PIXEL_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
);

const UNITS_MADE = 3;
// The jam takes two units of syrup for each unit it makes.
const SYRUP_PER_JAM = 2;

test.describe.configure({ mode: "serial" });

test.describe("Maker — the batches of a run", () => {
  let ctx: APIRequestContext;
  let api: ApiHelper;
  let token: string;
  let jamId: string;
  let jamName: string;
  let syrupId: string;
  let syrupName: string;
  let sugarId: string;
  let sugarName: string;
  let recipeId: string;
  let orderId: string;
  let firstSyrupBatch: { id: string; name: string };
  let chosenSyrupBatch: { id: string; name: string };
  let jamBatch: { id: string; name: string };
  const cleanup: Array<() => Promise<unknown>> = [];

  async function lotsOf(templateId: string) {
    const response = await ctx.get(
      `/api/v1/stock-lots?product_template_id=${templateId}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    expect(response.ok(), await response.text()).toBe(true);
    const body = (await response.json()) as {
      items: Array<{ id: string; name: string; status: string }>;
    };
    return body.items;
  }

  test.beforeAll(async ({ playwright, baseURL }, testInfo) => {
    ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
    await api.enableAllModules(token);

    const stamp = `${Date.now()}-w${testInfo.workerIndex}`;
    sugarName = `E2E-MB-Sugar-${stamp}`;
    syrupName = `E2E-MB-Syrup-${stamp}`;
    jamName = `E2E-MB-Jam-${stamp}`;
    const sugar = await api.createProductTemplate(token, { name: sugarName });
    const syrup = await api.createProductTemplate(token, { name: syrupName });
    const jam = await api.createProductTemplate(token, { name: jamName });
    sugarId = sugar.id;
    syrupId = syrup.id;
    jamId = jam.id;
    const shelf = await api.createStorage(token, {
      name: `E2E-MB-Shelf-${stamp}`,
    });

    const sugarStock = await api.seedStock(token, {
      product_template_id: sugar.id,
      product_template_name: sugarName,
      location_id: shelf.id,
      quantity: 100,
    });
    const syrupLine = await api.createBomLine(token, {
      parent_template_id: syrup.id,
      child_template_id: sugar.id,
      qty_per_batch: "2",
      unit: "kg",
    });
    const jamLine = await api.createBomLine(token, {
      parent_template_id: jam.id,
      child_template_id: syrup.id,
      qty_per_batch: String(SYRUP_PER_JAM),
      unit: "kg",
    });
    recipeId = await api.resolveDefaultRecipeId(token, jam.id);

    // Two batches of syrup, each enough for the whole jam run.
    for (let n = 0; n < 2; n++) {
      const run = await api.createProductionOrder(token, {
        output_template_id: syrup.id,
        planned_qty: "10",
        output_location_id: shelf.id,
      });
      await api.completeProductionOrder(token, run.id);
    }
    const syrupBatches = (await lotsOf(syrup.id)).sort((a, b) =>
      a.name.localeCompare(b.name),
    );
    expect(syrupBatches).toHaveLength(2);
    [firstSyrupBatch, chosenSyrupBatch] = syrupBatches;
    // A product made of ingredients is taken apart into them when a run needs
    // it. With its own formula gone the syrup is what it now is on the shelf: a
    // product kept in two batches, which is what the run is to choose from.
    await api.deleteBomLine(token, syrupLine.id);

    const draft = await api.createProductionOrder(token, {
      output_template_id: jam.id,
      planned_qty: String(UNITS_MADE),
      output_location_id: shelf.id,
    });
    orderId = draft.id;

    cleanup.push(
      () => api.deleteBomLine(token, jamLine.id),
      () => api.deleteItem(token, sugarStock.item_id),
    );
  });

  test.afterAll(async () => {
    for (const undo of cleanup) await undo().catch(() => {});
    await ctx.dispose();
  });

  test("closing the run takes the ingredient from the batch whose label was scanned", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto(`/maker/production/${orderId}`);
    await page.getByTestId("maker-detail-complete-button").click();

    const dialog = page.getByRole("alertdialog", {
      name: "Complete production run?",
    });
    const picker = dialog.getByTestId("maker-ingredient-batches");
    await expect(picker).toBeVisible({ timeout: 15000 });
    const select = dialog.getByTestId(`maker-batch-select-${syrupId}`);
    // Left alone, the run takes the default draw: nothing is chosen yet.
    await expect(select).toHaveValue("");

    // A code that is no ingredient's batch is refused in words.
    const scan = dialog.getByTestId("maker-batch-scan-input");
    await scan.fill("NO-SUCH-BATCH");
    await scan.press("Enter");
    await expect(
      dialog.getByText("No ingredient of this run has a batch NO-SUCH-BATCH"),
    ).toBeVisible();

    // The batch's own code picks that batch for the ingredient it belongs to.
    await scan.fill(chosenSyrupBatch.name);
    await scan.press("Enter");
    await expect(select).toHaveValue(chosenSyrupBatch.id);
    await expect(scan).toHaveValue("");

    const completed = page.waitForRequest(
      (request) =>
        request.method() === "POST" &&
        request.url().endsWith(`/orders/${orderId}/complete`),
    );
    await dialog.getByRole("button", { name: "Complete run" }).click();
    const body = (await completed).postDataJSON();
    expect(body.ingredient_lots).toEqual([
      expect.objectContaining({
        template_id: syrupId,
        lot_id: chosenSyrupBatch.id,
      }),
    ]);

    // The run filed its output under a batch of its own, which its card names.
    const card = page.getByTestId("maker-output-batch-card");
    await expect(card).toBeVisible({ timeout: 15000 });
    const made = await ctx.get(`/api/v1/maker/production/orders/${orderId}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const order = (await made.json()) as {
      status: string;
      output_lot_id: string;
      output_lot_name: string;
    };
    expect(order.status).toBe("COMPLETED");
    jamBatch = { id: order.output_lot_id, name: order.output_lot_name };
    await expect(page.getByTestId("maker-output-batch-code")).toContainText(
      jamBatch.name,
    );
  });

  test("the batch record names the output batch and the batch each ingredient came from", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto(`/maker/production/${orderId}`);
    await page.getByTestId("maker-open-batch-record").click();
    await expect(page).toHaveURL(
      new RegExp(`/maker/production/${orderId}/record$`),
    );

    const record = page.getByTestId("maker-batch-record");
    await expect(record).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("maker-record-batches")).toHaveText(
      jamBatch.name,
    );
    const ingredients = record.locator("section", {
      hasText: "Ingredients and their batches",
    });
    await expect(ingredients).toContainText(syrupName);
    await expect(ingredients).toContainText(chosenSyrupBatch.name);
    await expect(ingredients).not.toContainText(firstSyrupBatch.name);
    await expect(page.getByTestId("maker-print-batch-record")).toBeVisible();
  });

  test("the batch label sheet starts at one label per unit made and sends the ingredient list", async ({
    page,
    authenticatedPage,
  }) => {
    // The printer is announced the way an agent does it; one name, one printer.
    const register = await page.request.post(
      "/api/v1/printing/agent/register",
      {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          name: "E2E-Batch-Printer",
          printer_type: "zebra",
          agent_version: "1.0.0",
          protocol_version: 1,
        },
      },
    );
    expect(register.ok(), await register.text()).toBe(true);

    await page.goto(`/maker/production/${orderId}`);
    await page.getByTestId("maker-print-batch-labels").click();
    const sheet = page.getByRole("dialog", { name: /^(Batch|Jar) labels$/ });
    await expect(
      sheet.getByRole("img", { name: "Preview of one batch label" }),
    ).toBeVisible({ timeout: 15000 });

    // One label for each unit the run made.
    await expect(sheet.getByTestId("label-sheet-copies-input")).toHaveValue(
      String(UNITS_MADE),
    );
    await expect(
      sheet.getByRole("button", { name: `Download ${UNITS_MADE} labels` }),
    ).toBeVisible();

    // The jam is a made product, so its list is offered, and off until asked.
    const composition = sheet.getByRole("checkbox", {
      name: "Ingredients and allergens",
    });
    await expect(composition).toBeVisible();
    await expect(composition).not.toBeChecked();

    const preview = page.waitForRequest(
      (request) =>
        request.method() === "POST" &&
        request.url().endsWith("/printing/lot-labels/png") &&
        request.postDataJSON().composition === true,
    );
    await composition.check();
    const previewBody = (await preview).postDataJSON();
    expect(previewBody.lot_ids).toEqual([jamBatch.id]);
    await expect(
      sheet.getByRole("img", { name: "Preview of one batch label" }),
    ).toBeVisible();

    // The same labels, with the same list, go to the printer's queue.
    const queued = page.waitForRequest(
      (request) =>
        request.method() === "POST" && request.url().endsWith("/printing/jobs"),
    );
    await sheet.getByRole("button", { name: "Send to printer" }).click();
    const job = (await queued).postDataJSON();
    expect(job.lot_ids).toEqual([jamBatch.id]);
    expect(job.composition).toBe(true);
    expect(job.copies).toBe(UNITS_MADE);
    await expect(page.getByText("Sent to E2E-Batch-Printer")).toBeVisible();
  });

  test("a batch is put on hold with a reason and released again", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto(`/maker/production/${orderId}`);
    const card = page.getByTestId("maker-output-batch-card");
    await expect(card).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("maker-release-batch")).toHaveCount(0);

    await page.getByTestId("maker-hold-batch").click();
    const dialog = page.getByRole("alertdialog", {
      name: "Quarantine this batch?",
    });
    // Nobody puts a batch on hold without saying why.
    const confirm = dialog.getByRole("button", { name: "Quarantine" });
    await expect(confirm).toBeDisabled();
    await dialog.getByTestId("maker-hold-reason").fill("Lid seal looked loose");
    await confirm.click();

    await expect(card.getByText("Quarantined", { exact: true })).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByTestId("maker-hold-batch")).toHaveCount(0);
    expect(
      (await lotsOf(jamId)).find((b) => b.id === jamBatch.id)?.status,
    ).toBe("quarantined");

    await page.getByTestId("maker-release-batch").click();
    await expect(card.getByText("Quarantined", { exact: true })).toHaveCount(0, {
      timeout: 15000,
    });
    await expect(page.getByTestId("maker-hold-batch")).toBeVisible();
    expect(
      (await lotsOf(jamId)).find((b) => b.id === jamBatch.id)?.status,
    ).toBe("active");
  });

  test("a file is filed under the run, shows on its batch record and is removed", async ({
    page,
    authenticatedPage,
  }) => {
    const fileName = "jar-fill.png";
    await page.goto(`/maker/production/${orderId}`);
    const files = page.getByTestId("maker-run-attachments");
    await expect(files.getByText("No photos or files yet.")).toBeVisible({
      timeout: 15000,
    });

    await files
      .getByTestId("maker-run-attachment-input")
      .setInputFiles({
        name: fileName,
        mimeType: "image/png",
        buffer: PIXEL_PNG,
      });
    await expect(files.getByRole("link", { name: fileName })).toBeVisible({
      timeout: 15000,
    });

    // The record a person prints lists the files of the run.
    await page.getByTestId("maker-open-batch-record").click();
    await expect(
      page.getByTestId("maker-batch-record").getByText(fileName),
    ).toBeVisible({ timeout: 15000 });
    await page.goBack();

    await files.getByRole("button", { name: `Remove ${fileName}` }).click();
    await page
      .getByRole("alertdialog", { name: "Remove this file?" })
      .getByRole("button", { name: "Remove", exact: true })
      .click();
    await expect(files.getByText("No photos or files yet.")).toBeVisible({
      timeout: 15000,
    });
  });

  test("the BOM's Label tab lists what the made product is made of", async ({
    page,
    authenticatedPage,
  }) => {
    // The syrup is made of sugar again, as it was when its batches were made.
    const again = await api.createBomLine(token, {
      parent_template_id: syrupId,
      child_template_id: sugarId,
      qty_per_batch: "2",
      unit: "kg",
    });
    cleanup.push(() => api.deleteBomLine(token, again.id));

    await page.goto(`/maker/recipes/${recipeId}`);
    await page.getByRole("tab", { name: "Label" }).click();

    const label = page.getByTestId("maker-recipe-label");
    await expect(label).toBeVisible({ timeout: 15000 });
    // The syrup is a made ingredient: its own list follows it in brackets.
    await expect(label.getByTestId("maker-label-list")).toContainText(
      `${syrupName} (${sugarName})`,
    );
    await expect(label.getByText("Ingredients, heaviest first")).toBeVisible();
    await expect(label.getByText("Contains", { exact: true })).toBeVisible();
    await expect(label.getByText("Nutrition per 100 g")).toBeVisible();
  });
});
