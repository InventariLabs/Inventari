import { type Page } from "@playwright/test";
import { expect } from "./fixtures/auth";
import {
  defineStepTask,
  openLocationField,
  type StepEnv,
} from "./helpers/core-task";
import { arrivedField } from "./helpers/receive-screen";
import type { StepCounter } from "./helpers/step-counts";
import { showMoreUntilVisible } from "./helpers/todo-list";

/**
 * The floor's core tasks, walked the shortest way a person takes them from the
 * Start screen of Warehouse: receive a delivery, receive an order that is
 * waiting, issue to a customer, move goods between two locations, count a
 * shelf. Each is counted on a desktop and on a phone (`helpers/core-task.ts`),
 * and the outcome is read back through the API, so a walk that does not really
 * finish cannot come out shorter.
 *
 * A phone has its own path where the product gives it one: a delivery is
 * counted on the receiving session, a product is picked from the list the
 * search answers with and given its quantity before it joins the list.
 */

const PRODUCT_ON_SHELF = 20;

/** The shelf (or other location) a person picks from the location dialog. */
async function pickLocation(
  page: Page,
  steps: StepCounter,
  field: string,
  name: string,
) {
  await openLocationField(
    page.getByRole("combobox", { name: field, exact: true }),
    name,
    steps,
  );
  await pickFromDialog(page, name);
}

/** The partner dialog works the same way for suppliers and customers. */
async function pickPartner(page: Page, field: string, name: string) {
  await page.getByRole("combobox", { name: field, exact: true }).click();
  await pickFromDialog(page, name);
}

/**
 * A picker dialog gives the focus back to its field as it closes. The walk
 * goes on once it has: typed into the next field before that, the item search
 * lost the focus to the location field, closed its suggestions and took the
 * option out from under the click, on a loaded machine twice in four runs.
 */
async function pickFromDialog(page: Page, name: string) {
  const option = page.getByRole("button", { name, exact: true });
  await option.click();
  await expect(option).toBeHidden();
}

/**
 * The phone's receiving session books the delivery once the shelf is
 * confirmed: the label is scanned (here its code is typed, as a wedge scanner
 * would), then the count is closed as correct.
 */
async function finishOnReceivingSession(page: Page) {
  const session = page.getByRole("dialog");
  const code = (
    (await session.getByText(/^LOC-/).first().textContent()) ?? ""
  ).trim();
  const scan = session.getByRole("textbox", {
    name: /Scan the next product/,
  });
  await scan.fill(code);
  await scan.press("Enter");
  await expect(session.getByText("Scan the location to confirm")).toBeHidden();
  await session
    .getByRole("button", { name: "Correct, finish receiving" })
    .click();
}

async function seedShelf(env: StepEnv, label: string, stock = 0) {
  const name = `E2E-Steps-${label}-Shelf-${env.uid}`;
  const shelf = await env.api.createStorage(env.token, {
    name,
    location_type: "SHELF",
  });
  const product = `E2E-Steps-${label}-Goods-${env.uid}`;
  const template = await env.api.createProductTemplate(env.token, {
    name: product,
  });
  if (stock > 0) {
    await env.api.createItemForTemplate(env.token, {
      name: product,
      template_id: template.id,
      location_id: shelf.id,
      quantity: stock,
    });
  }
  return {
    shelfId: shelf.id,
    shelfName: name,
    product,
    templateId: template.id,
  };
}

async function documentsOf(
  env: StepEnv,
  partnerId: string,
  type: string,
): Promise<Array<{ status: string }>> {
  const all = await env.api.listDocuments(
    env.token,
    `partner_id=${partnerId}&type=${type}`,
  );
  return all.filter((document) => document.type === type);
}

// ---------------------------------------------------------------------------
// Receive a delivery
// ---------------------------------------------------------------------------

defineStepTask({
  task: "receive-delivery",
  title: "receive a delivery from a supplier, with no order waiting",
  start: "/warehouse/todo",
  seed: async (env) => {
    const where = await seedShelf(env, "Receive");
    const supplierName = `E2E-Steps-Receive-Supplier-${env.uid}`;
    const supplier = await env.api.createPartner(env.token, {
      name: supplierName,
      type: "SUPPLIER",
    });
    return { ...where, supplierName, supplierId: supplier.id, arrived: 4 };
  },
  walk: async (page, seed, viewport, steps) => {
    await page.getByRole("button", { name: /^Receive goods/ }).click();
    await pickPartner(page, "From", seed.supplierName);
    await pickLocation(page, steps, "To location", seed.shelfName);

    await page
      .getByRole("combobox", { name: "Scan or search a product" })
      .fill(seed.product);
    await page
      .getByRole("option", { name: new RegExp(seed.product) })
      .first()
      .click();

    if (viewport === "desktop") {
      await page
        .getByLabel(`How many arrived: ${seed.product}`)
        .fill(String(seed.arrived));
      await page.getByRole("button", { name: "Receive into stock" }).click();
      await expect(
        page.getByRole("heading", { name: "Received 1 line" }),
      ).toBeVisible({ timeout: 15000 });
      return;
    }

    // The phone counts the delivery on the receiving session: the sheet only
    // names the goods and how many, the session books them.
    await page
      .getByRole("spinbutton", { name: `How many arrived: ${seed.product}` })
      .fill(String(seed.arrived));
    await page
      .getByRole("button", { name: "Receive one product at a time" })
      .click();
    await finishOnReceivingSession(page);
    await expect(
      page.getByRole("button", { name: "Undo receipt" }).first(),
    ).toBeVisible({
      timeout: 15000,
    });
  },
  verify: async (env, seed) => {
    await expect
      .poll(() =>
        env.api.quantityOnHand(env.token, seed.templateId, seed.shelfId),
      )
      .toBe(seed.arrived);
    const receipts = await documentsOf(env, seed.supplierId, "IN");
    expect(receipts.map((receipt) => receipt.status)).toEqual(["COMPLETED"]);
  },
});

// ---------------------------------------------------------------------------
// Receive an order that is waiting
// ---------------------------------------------------------------------------

defineStepTask({
  task: "receive-from-order",
  title: "receive a delivery that a confirmed purchase order is waiting for",
  start: "/warehouse/todo",
  seed: async (env) => {
    const where = await seedShelf(env, "Order");
    const supplierName = `E2E-Steps-Order-Supplier-${env.uid}`;
    const supplier = await env.api.createPartner(env.token, {
      name: supplierName,
      type: "SUPPLIER",
    });
    const ordered = 6;
    const order = await env.api.createPurchaseOrder(env.token, {
      partner_id: supplier.id,
      status: "DRAFT",
      lines: [
        {
          product_template_id: where.templateId,
          quantity_ordered: ordered,
          unit_price: "2.00",
        },
      ],
    });
    const confirmed = await env.api.confirmPurchaseOrder(env.token, order.id);
    expect(confirmed.status).toBe("CONFIRMED");
    return { ...where, supplierName, supplierId: supplier.id, ordered };
  },
  walk: async (page, seed, viewport, steps) => {
    // The order is a task on the Start screen: one press opens the receipt
    // with the supplier, the goods and the counts filled in from it.
    const task = page
      .getByText(`Receive delivery from ${seed.supplierName}`)
      .locator("xpath=ancestor::*[.//button or self::button][1]");
    // The shared database holds more than a hundred older tasks; asking for
    // the rest of the list is the database's doing, not a step of the task.
    await steps.uncounted(() =>
      showMoreUntilVisible(
        page,
        page.getByText(`Receive delivery from ${seed.supplierName}`),
      ),
    );
    await task
      .getByRole("button", {
        name: viewport === "desktop" ? "Receive delivery" : "Receive",
      })
      .click();
    await pickLocation(page, steps, "To location", seed.shelfName);

    if (viewport === "desktop") {
      // The order's lines arrive after the destination is chosen; pressing
      // before they do posts an empty sheet ("Add at least one line").
      await expect(arrivedField(page, seed.product)).toHaveValue(
        String(seed.ordered),
        { timeout: 15000 },
      );
      await page.getByRole("button", { name: "Receive into stock" }).click();
      await expect(
        page.getByRole("heading", { name: "Received 1 line" }),
      ).toBeVisible({ timeout: 15000 });
      return;
    }

    await page
      .getByRole("button", { name: "Receive one product at a time" })
      .click();
    await finishOnReceivingSession(page);
    await expect(
      page.getByRole("button", { name: "Undo receipt" }).first(),
    ).toBeVisible({
      timeout: 15000,
    });
  },
  verify: async (env, seed) => {
    await expect
      .poll(() =>
        env.api.quantityOnHand(env.token, seed.templateId, seed.shelfId),
      )
      .toBe(seed.ordered);
    const receipts = await documentsOf(env, seed.supplierId, "IN");
    expect(receipts.map((receipt) => receipt.status)).toEqual(["COMPLETED"]);
  },
});

// ---------------------------------------------------------------------------
// Issue to a customer
// ---------------------------------------------------------------------------

defineStepTask({
  task: "issue-to-customer",
  title: "issue goods to a customer",
  start: "/warehouse/todo",
  seed: async (env) => {
    const where = await seedShelf(env, "Issue", PRODUCT_ON_SHELF);
    const customerName = `E2E-Steps-Issue-Customer-${env.uid}`;
    const customer = await env.api.createPartner(env.token, {
      name: customerName,
      type: "CUSTOMER",
    });
    return { ...where, customerName, customerId: customer.id, sent: 3 };
  },
  walk: async (page, seed, viewport, steps) => {
    await page.getByRole("button", { name: /^Issue goods/ }).click();
    await pickPartner(page, "Customer", seed.customerName);
    await pickLocation(page, steps, "From location", seed.shelfName);

    if (viewport === "desktop") {
      await page
        .getByRole("combobox", { name: "Item", exact: true })
        .fill(seed.product);
      await page
        .getByRole("option", { name: new RegExp(seed.product) })
        .first()
        .click();
      await page
        .getByRole("spinbutton", { name: "Quantity" })
        .fill(String(seed.sent));
    } else {
      // The phone answers a search with the products that stand on the
      // chosen shelf, and asks how many before the product joins the list.
      await page
        .getByRole("textbox", { name: "Scan or type a name" })
        .fill(seed.product);
      await page
        .getByRole("button", { name: new RegExp(`^${seed.product}`) })
        .click();
      await page
        .getByRole("spinbutton", { name: `How many: ${seed.product}` })
        .fill(String(seed.sent));
      await page.getByRole("button", { name: "Add", exact: true }).click();
    }

    await page.getByRole("button", { name: "Issue to the customer" }).click();
    await expect(
      page.getByRole("heading", { name: "Issued 1 line" }),
    ).toBeVisible({ timeout: 15000 });
  },
  verify: async (env, seed) => {
    await expect
      .poll(() =>
        env.api.quantityOnHand(env.token, seed.templateId, seed.shelfId),
      )
      .toBe(PRODUCT_ON_SHELF - seed.sent);
    const deliveries = await documentsOf(env, seed.customerId, "OUT");
    expect(deliveries.map((delivery) => delivery.status)).toEqual([
      "COMPLETED",
    ]);
  },
});

// ---------------------------------------------------------------------------
// Move between locations
// ---------------------------------------------------------------------------

defineStepTask({
  task: "move-between-locations",
  title: "move goods from one location to another",
  start: "/warehouse/todo",
  seed: async (env) => {
    const from = await seedShelf(env, "MoveFrom", PRODUCT_ON_SHELF);
    const to = await env.api.createStorage(env.token, {
      name: `E2E-Steps-MoveTo-Shelf-${env.uid}`,
      location_type: "SHELF",
    });
    return {
      ...from,
      toId: to.id,
      toName: `E2E-Steps-MoveTo-Shelf-${env.uid}`,
      moved: 5,
    };
  },
  walk: async (page, seed, viewport, steps) => {
    await page.getByRole("button", { name: /^Move/ }).click();
    await pickLocation(page, steps, "From location", seed.shelfName);
    await pickLocation(page, steps, "To location", seed.toName);

    if (viewport === "desktop") {
      await page
        .getByRole("combobox", { name: "Item", exact: true })
        .fill(seed.product);
      await page
        .getByRole("option", { name: new RegExp(seed.product) })
        .first()
        .click();
      await page
        .getByRole("spinbutton", { name: "Quantity" })
        .fill(String(seed.moved));
    } else {
      await page
        .getByRole("textbox", { name: "Scan or type a name" })
        .fill(seed.product);
      await page
        .getByRole("button", { name: new RegExp(`^${seed.product}`) })
        .click();
      await page
        .getByRole("spinbutton", { name: `How many: ${seed.product}` })
        .fill(String(seed.moved));
      await page.getByRole("button", { name: "Add", exact: true }).click();
    }

    await page.getByRole("button", { name: "Move", exact: true }).click();
    await expect(page.getByRole("heading", { name: /^Moved / })).toBeVisible({
      timeout: 15000,
    });
  },
  verify: async (env, seed) => {
    await expect
      .poll(() => env.api.quantityOnHand(env.token, seed.templateId, seed.toId))
      .toBe(seed.moved);
    expect(
      await env.api.quantityOnHand(env.token, seed.templateId, seed.shelfId),
    ).toBe(PRODUCT_ON_SHELF - seed.moved);
  },
});

// ---------------------------------------------------------------------------
// Count a shelf
// ---------------------------------------------------------------------------

defineStepTask({
  task: "count-a-shelf",
  title: "count one shelf and post the difference",
  start: "/warehouse/todo",
  seed: async (env) => {
    const where = await seedShelf(env, "Count", 10);
    return { ...where, counted: 8 };
  },
  walk: async (page, seed, _viewport, steps) => {
    await page.getByRole("button", { name: /^Count/ }).click();
    // The list opens on the first page of locations by name, which holds a
    // clean database's; the shared one holds more, so the name is typed
    // without counting it (see openLocationField).
    const find = page.getByRole("textbox", { name: "Find a location" });
    await steps.uncounted(async () => {
      await find.fill(seed.shelfName);
      await find.blur();
    });
    await page
      .getByRole("button", { name: new RegExp(`^${seed.shelfName} `) })
      .click();
    await page.getByRole("button", { name: `Count ${seed.shelfName}` }).click();

    await page
      .getByRole("textbox", { name: `Counted quantity of ${seed.product}` })
      .fill(String(seed.counted));
    await page
      .getByRole("button", { name: `Save the count for ${seed.product}` })
      .click();
    // Completing refuses, with a toast and no dialog, while the saved number
    // has not come back from the server: the button greys out when it is
    // pressed, long before the card agrees with the record. The difference
    // is the server's verdict, so its filter button is what says the stock
    // take has been read again.
    await expect(
      page.getByRole("button", { name: "Discrepancies (1)" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Complete stock take" }).click();
    const confirmation = page.getByRole("alertdialog");
    await confirmation
      .getByRole("button", { name: "Complete", exact: true })
      .click();
    await expect(
      page.getByText("The differences were posted as stock adjustment"),
    ).toBeVisible({ timeout: 15000 });
  },
  verify: async (env, seed) => {
    await expect
      .poll(() =>
        env.api.quantityOnHand(env.token, seed.templateId, seed.shelfId),
      )
      .toBe(seed.counted);
  },
});
