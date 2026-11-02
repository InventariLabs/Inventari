import { expect } from "./fixtures/auth";
import {
  defineStepTask,
  openLocationField,
  type StepEnv,
} from "./helpers/core-task";

/**
 * Four core tasks of the office side of the warehouse, each walked the
 * shortest way a person takes it and counted by the page (see
 * `helpers/step-counts.ts`). The outcome of every walk is read from the API,
 * so a walk that stops short of the result cannot pass with a short count.
 */

/** A shelf of its own, so no other spec's stock is in the way. */
async function shelf(env: StepEnv, label: string) {
  return env.api.createStorageIdempotent(env.token, {
    name: `E2E-Steps-${label}-${env.uid}`,
    location_type: "SHELF",
  });
}

defineStepTask({
  task: "undo-a-mistake",
  title: "undo a receipt that was posted by mistake",
  start: "/warehouse/todo",
  async seed(env) {
    const place = await shelf(env, "Undo");
    const name = `E2E-Steps-Undo-Goods-${env.uid}`;
    const template = await env.api.createProductTemplate(env.token, { name });
    const supplier = await env.api.createPartner(env.token, {
      name: `E2E-Steps-Undo-Supplier-${env.uid}`,
      type: "SUPPLIER",
    });
    const draft = await env.api.createDocument(env.token, {
      type: "IN",
      partner_id: supplier.id,
      target_location_id: place.id,
      lines: [{ product_template_id: template.id, expected_quantity: 5 }],
    });
    await env.api.confirmDocument(env.token, draft.id);
    await env.api.completeDocument(env.token, draft.id);
    const posted = await env.api.getDocument(env.token, draft.id);
    return {
      documentId: draft.id,
      number: String(posted.number),
      templateId: template.id,
      shelfId: place.id,
    };
  },
  async walk(page, seed) {
    // The receipt is in today's activity on the Start screen: one click to
    // its page, where Undo is.
    await page.getByRole("link", { name: seed.number, exact: true }).click();
    await page.getByRole("button", { name: "Undo receipt" }).click();
    await page
      .getByRole("alertdialog", { name: "Undo this document?" })
      .getByRole("button", { name: "Undo", exact: true })
      .click();
    // The reversal is a posting: on a loaded machine it outlasted the 5 s
    // default, with the button still waiting on it.
    await expect(page.getByText(/Undone — reversal/).first()).toBeVisible({
      timeout: 15000,
    });
  },
  async verify(env, seed) {
    await expect
      .poll(() =>
        env.api.quantityOnHand(env.token, seed.templateId, seed.shelfId),
      )
      .toBe(0);
  },
});

defineStepTask({
  task: "find-a-product",
  title: "find where a product lies",
  start: "/warehouse/todo",
  async seed(env) {
    const place = await shelf(env, "Find");
    const name = `E2E-Steps-Find-Goods-${env.uid}`;
    const template = await env.api.createProductTemplate(env.token, { name });
    await env.api.createItemForTemplate(env.token, {
      name,
      template_id: template.id,
      location_id: place.id,
      quantity: 4,
    });
    return {
      name,
      shelfName: `E2E-Steps-Find-${env.uid}`,
      templateId: template.id,
      shelfId: place.id,
    };
  },
  async walk(page, seed) {
    // Start links to the stock list; typing the name leaves one row, and the
    // row says where the product lies.
    await page.getByRole("link", { name: "Stock", exact: true }).click();
    await page.getByPlaceholder("Search a product or a batch…").fill(seed.name);
    // A phone draws cards where a desktop draws a table; only one of the two
    // is visible, and either says the product and where it lies.
    await expect(
      page.getByText(seed.name).filter({ visible: true }).first(),
    ).toBeVisible();
    await expect(
      page.getByText(seed.shelfName).filter({ visible: true }).first(),
    ).toBeVisible();
  },
  async verify(env, seed) {
    // The screen showed the shelf the stock really is on.
    expect(
      await env.api.quantityOnHand(env.token, seed.templateId, seed.shelfId),
    ).toBe(4);
  },
});

defineStepTask({
  task: "add-first-product",
  title: "add a first product",
  start: "/",
  async seed(env) {
    await shelf(env, "First");
    return {
      name: `E2E-Steps-First-Product-${env.uid}`,
      shelfName: `E2E-Steps-First-${env.uid}`,
    };
  },
  async walk(page, seed, _viewport, steps) {
    await page.getByRole("link", { name: /^Inventory/ }).click();
    await page.getByRole("button", { name: "Add product" }).click();
    await page.getByRole("textbox", { name: /product name/i }).fill(seed.name);
    await openLocationField(
      page.getByRole("combobox", { name: /location/i }),
      seed.shelfName,
      steps,
    );
    // The picker lists the locations as buttons; the one wanted is chosen,
    // not searched for, which is what a person with a handful of locations does.
    await page
      .getByRole("button", { name: new RegExp(`^${seed.shelfName}`) })
      .click();
    await page.getByRole("button", { name: "Add Product" }).click();
    await expect(page).toHaveURL(/\/inventory\/items$/);
  },
  async verify(env, seed) {
    await expect
      .poll(
        async () => (await env.api.searchProducts(env.token, seed.name)).length,
      )
      .toBeGreaterThan(0);
  },
});

defineStepTask({
  task: "record-i-made-it",
  title: "record that something was made",
  start: "/",
  async seed(env) {
    const place = await shelf(env, "Made");
    const output = await env.api.createProductTemplate(env.token, {
      name: `E2E-Steps-Made-Loaf-${env.uid}`,
    });
    const flourName = `E2E-Steps-Made-Flour-${env.uid}`;
    const flour = await env.api.createProductTemplate(env.token, {
      name: flourName,
    });
    await env.api.createBomLine(env.token, {
      parent_template_id: output.id,
      child_template_id: flour.id,
      qty_per_batch: "2",
      unit: "pcs",
    });
    await env.api.seedStock(env.token, {
      product_template_id: flour.id,
      product_template_name: flourName,
      location_id: place.id,
      quantity: 20,
    });
    return {
      outputName: `E2E-Steps-Made-Loaf-${env.uid}`,
      outputId: output.id,
      shelfName: `E2E-Steps-Made-${env.uid}`,
    };
  },
  async walk(page, seed, _viewport, steps) {
    // Production opens on the formulas; the card of the product has Produce.
    await page.getByRole("link", { name: /^Production/ }).click();
    await page
      .locator("div")
      .filter({ has: page.getByText(seed.outputName, { exact: true }) })
      .filter({ has: page.getByRole("button", { name: "Produce" }) })
      .last()
      .getByRole("button", { name: "Produce" })
      .click();
    const sheet = page.getByRole("dialog", { name: "Record production" });
    await sheet.getByTestId("maker-create-qty-input").fill("2");
    await openLocationField(
      sheet.getByRole("combobox", { name: /to location/i }),
      seed.shelfName,
      steps,
    );
    await page
      .getByRole("button", { name: new RegExp(seed.shelfName) })
      .last()
      .click();
    await sheet.getByRole("button", { name: "Save as made" }).click();
    await expect(page.getByText("Production recorded").first()).toBeVisible();
  },
  async verify(env, seed) {
    await expect
      .poll(async () => {
        const runs = await env.api.listProductionOrders(env.token, {
          output_template_id: seed.outputId,
        });
        return runs.map((run) => run.status);
      })
      .toEqual(["COMPLETED"]);
  },
});
