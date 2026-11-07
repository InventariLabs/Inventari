import { setShelfScanRule } from "./helpers/shelf-scan-rule";
import { type Page } from "@playwright/test";
import { test, expect } from "./fixtures/camera";
import {
  startSeed,
  type ReceivingSeed,
  type SeededOrder,
  type SeededPartner,
  type SeededProduct,
  type SeededShelf,
} from "./helpers/receive-seed";
import {
  chooseLocation,
  choosePartner,
  countField,
  scanProduct,
  scanShelf,
  session,
} from "./helpers/receive-screen";

/**
 * Receiving on a phone, from the two doors that lead to it.
 *
 * At 390x844 the Receive screen does not list the delivery: choosing the
 * supplier and the location and pressing "Receive one product at a time" saves
 * the receipt, confirms it and opens the receiving session, which walks the
 * goods one by one with the camera, a count and a location to confirm. The
 * route's component tests stub that session; this walks it for real, from
 * Start and from a To do task, and reads the ledger and the order afterwards,
 * because the claim is that the shelf is right and the order still waits for
 * what did not come.
 */

test.use({
  viewport: { width: 390, height: 844 },
  hasTouch: true,
  isMobile: true,
});

/**
 * The row of a To do task, found whatever page of the list it is on: the
 * nearest block around its sentence that holds the task's button.
 */
async function taskRow(page: Page, sentence: string) {
  const text = page.getByText(sentence);
  const more = page.getByRole("button", { name: "Show more" });
  for (let i = 0; i < 20; i++) {
    if ((await text.count()) > 0) break;
    if (!(await more.isVisible())) break;
    await more.click();
  }
  return text.locator("xpath=ancestor::div[.//button][1]");
}

async function openFromStart(page: Page) {
  await page.goto("/warehouse/todo");
  await page.getByRole("button", { name: "Receive goods" }).click();
  await expect(
    page.getByRole("heading", { name: "Receive goods", level: 1 }),
  ).toBeVisible();
}

async function openSession(page: Page, supplier: string, shelf: string) {
  await chooseLocation(page, shelf);
  await page
    .getByRole("button", { name: "Receive one product at a time" })
    .click();
  await expect(page).toHaveURL(/\/warehouse\/documents\/[^/]+#receive/);
  await expect(session(page).getByRole("heading", { level: 2 })).toContainText(
    `Delivery from ${supplier}`,
  );
}

interface Delivery {
  seed: ReceivingSeed;
  shelf: SeededShelf;
  supplier: SeededPartner;
  rice: SeededProduct;
  beans: SeededProduct;
  order: SeededOrder;
}

/** A supplier whose order waits: ten rice and six beans. */
async function waitingDelivery(
  seed: ReceivingSeed,
  quantities = { rice: 10, beans: 6 },
): Promise<Delivery> {
  const shelf = await seed.shelf("Shelf");
  const supplier = await seed.partner("Supplier", "SUPPLIER");
  const rice = await seed.product("Rice");
  const beans = await seed.product("Beans");
  const order = await seed.order(supplier, [
    { product: rice, quantity: quantities.rice },
    { product: beans, quantity: quantities.beans },
  ]);
  return { seed, shelf, supplier, rice, beans, order };
}

test.describe("Receiving on a phone", () => {
  // These walks are about the shelf being confirmed by scan before a session
  // moves on, which is a rule of the whole organisation: the file runs in the
  // one-worker project and puts the rule back as it found it.
  let askedBefore = false;
  test.beforeAll(async ({ playwright, baseURL }) => {
    askedBefore = await setShelfScanRule(playwright, baseURL, true);
  });
  test.afterAll(async ({ playwright, baseURL }) => {
    await setShelfScanRule(playwright, baseURL, askedBefore);
  });

  test("from Start, a partial delivery books what arrived and leaves the rest expected", async ({
    page,
    playwright,
    baseURL,
    authenticatedPage: _auth,
  }, testInfo) => {
    const seed = await startSeed({ playwright }, baseURL, testInfo);
    const d = await waitingDelivery(seed);

    await openFromStart(page);
    await choosePartner(page, d.supplier.name);
    await expect(
      page.getByText(`${d.order.number} expects 2 lines.`),
    ).toBeVisible();
    await openSession(page, d.supplier.name, d.shelf.name);

    // First card: the rice, ordered ten. Only six came.
    const dialog = session(page);
    await expect(dialog.getByText("0 of 2", { exact: true })).toBeVisible();
    await expect(dialog.getByText("Still due 10 pcs.")).toBeVisible();
    await countField(page, d.rice.name).fill("6");
    await expect(
      dialog.getByText("4 pcs. missing. It stays expected on the order."),
    ).toBeVisible();

    // The location is confirmed by scanning it; a count cannot move on before.
    await dialog.getByRole("button", { name: "Correct, next" }).click();
    await expect(page.getByText(/Scan the location first/)).toBeVisible();
    await expect(dialog.getByText("0 of 2", { exact: true })).toBeVisible();
    await scanShelf(page, d.shelf.code);
    await dialog.getByRole("button", { name: "Correct, next" }).click();

    // Second card: the beans arrived in full, and the confirmed shelf holds.
    await expect(dialog.getByText("1 of 2", { exact: true })).toBeVisible();
    await expect(dialog.getByText("Still due 6 pcs.")).toBeVisible();
    await expect(countField(page, d.beans.name)).toHaveValue("6");
    await expect(
      dialog.getByText("Location confirmed", { exact: true }),
    ).toBeVisible();
    await dialog
      .getByRole("button", { name: "Correct, finish receiving" })
      .click();

    await expect(
      dialog.getByRole("heading", { name: "Received 2 lines" }),
    ).toBeVisible({ timeout: 15000 });
    await expect(
      dialog.getByText(
        "2 of 2 lines arrived and are in stock. What did not come stays expected on the order.",
      ),
    ).toBeVisible();

    // The ledger holds what was counted, and the order what is still owed.
    expect(await seed.onHand(d.rice, d.shelf)).toBe(6);
    expect(await seed.onHand(d.beans, d.shelf)).toBe(6);
    const lines = await seed.orderLines(d.order);
    expect(lines.find((l) => l.name === d.rice.name)).toMatchObject({
      ordered: 10,
      received: 6,
    });
    expect(lines.find((l) => l.name === d.beans.name)).toMatchObject({
      ordered: 6,
      received: 6,
    });

    // The next delivery comes in on a fresh load of the screen: the same
    // order is waiting, for the rice only.
    await expect(
      dialog.getByRole("button", { name: "Receive more" }),
    ).toBeVisible();
    await page.goto("/warehouse/receive");
    await choosePartner(page, d.supplier.name);
    await expect(
      page.getByText(`${d.order.number} expects 1 line.`),
    ).toBeVisible();
    await openSession(page, d.supplier.name, d.shelf.name);
    await expect(
      session(page).getByText("0 of 1", { exact: true }),
    ).toBeVisible();
    await expect(session(page).getByText("Still due 4 pcs.")).toBeVisible();
    await scanShelf(page, d.shelf.code);
    await session(page)
      .getByRole("button", { name: "Correct, finish receiving" })
      .click();
    await expect(
      session(page).getByRole("heading", { name: "Received 1 line" }),
    ).toBeVisible({ timeout: 15000 });

    // The rest arrived: the order is received in full.
    expect(await seed.onHand(d.rice, d.shelf)).toBe(10);
    const after = await seed.orderLines(d.order);
    expect(after.map((l) => l.received)).toEqual([10, 6]);
    expect(await seed.orderStatus(d.order)).not.toBe("CONFIRMED");
  });

  test("from To do, the Receive delivery task opens the receipt on its order", async ({
    page,
    playwright,
    baseURL,
    authenticatedPage: _auth,
  }, testInfo) => {
    const seed = await startSeed({ playwright }, baseURL, testInfo);
    const d = await waitingDelivery(seed, { rice: 5, beans: 3 });

    await page.goto("/warehouse/todo");
    const row = await taskRow(page, `Receive delivery from ${d.supplier.name}`);
    await expect(row).toBeVisible();
    await row.getByRole("button", { name: "Receive delivery" }).click();

    // The order's own lines on the receive screen: the supplier is filled in
    // by the link, the order is named, nothing else has to be typed.
    await expect(page).toHaveURL(
      new RegExp(`/warehouse/receive\\?order=${d.order.id}`),
    );
    await expect(page.getByRole("combobox", { name: "From" })).toContainText(
      d.supplier.name,
    );
    await expect(
      page.getByText(`${d.order.number} expects 2 lines.`),
    ).toBeVisible();

    await chooseLocation(page, d.shelf.name);
    await page
      .getByRole("button", { name: "Receive one product at a time" })
      .click();
    await expect(page).toHaveURL(/#receive/);
    const dialog = session(page);
    await expect(dialog.getByText("Still due 5 pcs.")).toBeVisible();
    await scanShelf(page, d.shelf.code);
    await dialog.getByRole("button", { name: "Correct, next" }).click();
    await expect(dialog.getByText("Still due 3 pcs.")).toBeVisible();
    await dialog
      .getByRole("button", { name: "Correct, finish receiving" })
      .click();
    await expect(
      dialog.getByRole("heading", { name: "Received 2 lines" }),
    ).toBeVisible({ timeout: 15000 });

    expect(await seed.onHand(d.rice, d.shelf)).toBe(5);
    expect(await seed.onHand(d.beans, d.shelf)).toBe(3);
    expect((await seed.orderLines(d.order)).map((l) => l.received)).toEqual([
      5, 3,
    ]);

    // The task is done: the order no longer waits on the To do list.
    await page.goto("/warehouse/todo");
    await expect(
      page
        .getByRole("region", { name: "Tasks" })
        .getByText(`Receive delivery from ${d.supplier.name}`),
    ).toHaveCount(0);
  });

  test("the rest did not come: finishing early books only what was counted", async ({
    page,
    playwright,
    baseURL,
    authenticatedPage: _auth,
  }, testInfo) => {
    const seed = await startSeed({ playwright }, baseURL, testInfo);
    const d = await waitingDelivery(seed, { rice: 5, beans: 3 });

    await openFromStart(page);
    await choosePartner(page, d.supplier.name);
    await openSession(page, d.supplier.name, d.shelf.name);
    const dialog = session(page);

    await scanShelf(page, d.shelf.code);
    await dialog.getByRole("button", { name: "Correct, next" }).click();
    await expect(dialog.getByText("Still due 3 pcs.")).toBeVisible();

    await dialog
      .getByRole("button", { name: "The rest did not come — finish" })
      .click();
    await expect(
      page.getByRole("heading", { name: "Finish without the rest?" }),
    ).toBeVisible();
    await expect(
      page.getByText(
        /1 line is not confirmed\. What was scanned of it is received/,
      ),
    ).toBeVisible();
    // Keeping on returns to the card without booking anything.
    await page.getByRole("button", { name: "Keep receiving" }).click();
    await expect(dialog.getByText("Still due 3 pcs.")).toBeVisible();
    expect(await seed.onHand(d.rice, d.shelf)).toBe(0);

    await dialog
      .getByRole("button", { name: "The rest did not come — finish" })
      .click();
    await page.getByRole("button", { name: "Finish receiving" }).click();
    await expect(
      dialog.getByRole("heading", { name: "Received 1 line" }),
    ).toBeVisible({ timeout: 15000 });
    await expect(
      dialog.getByText(
        "1 of 2 lines arrived and are in stock. What did not come stays expected on the order.",
      ),
    ).toBeVisible();

    expect(await seed.onHand(d.rice, d.shelf)).toBe(5);
    expect(await seed.onHand(d.beans, d.shelf)).toBe(0);
    const lines = await seed.orderLines(d.order);
    expect(lines.map((l) => l.received)).toEqual([5, 0]);
    expect(await seed.orderStatus(d.order)).toBe("CONFIRMED");
  });

  test("goods nobody ordered are scanned in, counted and put away", async ({
    page,
    playwright,
    baseURL,
    authenticatedPage: _auth,
  }, testInfo) => {
    const seed = await startSeed({ playwright }, baseURL, testInfo);
    const shelf = await seed.shelf("Shelf");
    const supplier = await seed.partner("Supplier", "SUPPLIER");
    const rice = await seed.product("Rice");
    const beans = await seed.product("Beans");

    await openFromStart(page);
    await choosePartner(page, supplier.name);
    await chooseLocation(page, shelf.name);
    await expect(
      page.getByText("No order from this supplier is waiting."),
    ).toBeVisible();
    await expect(
      page.getByText(/Nothing was ordered: scan each product/),
    ).toBeVisible();

    // Nothing to start on yet: the goods are taken in first, as a wedge types them.
    await scanProduct(page, rice.barcode, rice.name);
    await scanProduct(page, beans.barcode, beans.name);
    const riceCount = page.getByRole("spinbutton", {
      name: `How many arrived: ${rice.name}`,
    });
    await expect(riceCount).toHaveValue("1");
    const increase = page.getByRole("button", { name: "Increase" }).first();
    await increase.click();
    await increase.click();
    await expect(riceCount).toHaveValue("3");

    await page
      .getByRole("button", { name: "Receive one product at a time" })
      .click();
    await expect(page).toHaveURL(/#receive/);
    const dialog = session(page);
    // No order to speak of: the count somebody wrote down is "expected".
    await expect(dialog.getByText("Expected 3 pcs.")).toBeVisible();
    await expect(dialog.getByText(/^Still due /)).toHaveCount(0);
    await scanShelf(page, shelf.code);
    await dialog.getByRole("button", { name: "Correct, next" }).click();
    await expect(dialog.getByText("Expected 1 pcs.")).toBeVisible();
    await dialog
      .getByRole("button", { name: "Correct, finish receiving" })
      .click();
    await expect(
      dialog.getByRole("heading", { name: "Received 2 lines" }),
    ).toBeVisible({ timeout: 15000 });

    expect(await seed.onHand(rice, shelf)).toBe(3);
    expect(await seed.onHand(beans, shelf)).toBe(1);
    // The document names no order: it is the supplier's receipt, and the
    // office is told so.
    const posted = await seed.documentLinkedFrom(dialog);
    expect(posted).toMatchObject({ type: "IN", partner_id: supplier.id });
  });

  test("goods nobody ordered take the true count raised on the card", async ({
    page,
    playwright,
    baseURL,
    authenticatedPage: _auth,
  }, testInfo) => {
    const seed = await startSeed({ playwright }, baseURL, testInfo);
    const shelf = await seed.shelf("Shelf");
    const supplier = await seed.partner("Supplier", "SUPPLIER");
    const sugar = await seed.product("Sugar");

    await openFromStart(page);
    await choosePartner(page, supplier.name);
    await chooseLocation(page, shelf.name);
    // The row starts at 1; five came, which nobody could have ordered.
    await scanProduct(page, sugar.barcode, sugar.name);
    await page
      .getByRole("button", { name: "Receive one product at a time" })
      .click();
    await expect(page).toHaveURL(/#receive/);
    const dialog = session(page);
    await scanShelf(page, shelf.code);
    await countField(page, sugar.name).fill("5");
    await dialog
      .getByRole("button", { name: "Correct, finish receiving" })
      .click();

    // Not "exceeds the tolerance": there was nothing to exceed.
    await expect(
      dialog.getByRole("heading", { name: "Received 1 line" }),
    ).toBeVisible({ timeout: 15000 });
    expect(await seed.onHand(sugar, shelf)).toBe(5);
  });

  test("an ordered and an extra product from one supplier are both booked", async ({
    page,
    playwright,
    baseURL,
    authenticatedPage: _auth,
  }, testInfo) => {
    const seed = await startSeed({ playwright }, baseURL, testInfo);
    const shelf = await seed.shelf("Shelf");
    const supplier = await seed.partner("Supplier", "SUPPLIER");
    const rice = await seed.product("Rice");
    const sugar = await seed.product("Sugar");
    const order = await seed.order(supplier, [{ product: rice, quantity: 4 }]);

    await openFromStart(page);
    await choosePartner(page, supplier.name);
    await expect(
      page.getByText(`${order.number} expects 1 line.`),
    ).toBeVisible();
    await chooseLocation(page, shelf.name);
    // The sugar is not on the order: it joins the delivery as a line of its own.
    await scanProduct(page, sugar.barcode, sugar.name);

    await page
      .getByRole("button", { name: "Receive one product at a time" })
      .click();
    await expect(page).toHaveURL(/#receive/);
    const dialog = session(page);
    await expect(dialog.getByText("0 of 2", { exact: true })).toBeVisible();

    // The ordered line comes first, with what is still due on it.
    await expect(dialog.getByRole("region", { name: rice.name })).toBeVisible();
    await expect(dialog.getByText("Still due 4 pcs.")).toBeVisible();
    await scanShelf(page, shelf.code);
    await dialog.getByRole("button", { name: "Correct, next" }).click();

    // Then the extra one, which nothing is due on.
    await expect(
      dialog.getByRole("region", { name: sugar.name }),
    ).toBeVisible();
    await expect(dialog.getByText(/^Still due /)).toHaveCount(0);
    await countField(page, sugar.name).fill("2");
    await dialog
      .getByRole("button", { name: "Correct, finish receiving" })
      .click();
    await expect(
      dialog.getByRole("heading", { name: "Received 2 lines" }),
    ).toBeVisible({ timeout: 15000 });

    // Both reached the shelf; the order shows only its own line as received.
    expect(await seed.onHand(rice, shelf)).toBe(4);
    expect(await seed.onHand(sugar, shelf)).toBe(2);
    const lines = await seed.orderLines(order);
    expect(lines).toHaveLength(1);
    expect(lines[0]).toMatchObject({ ordered: 4, received: 4 });
    expect(await seed.orderStatus(order)).not.toBe("CONFIRMED");
  });

  test("the camera in the session reads the next product", async ({
    page,
    camera,
    playwright,
    baseURL,
  }, testInfo) => {
    const seed = await startSeed({ playwright }, baseURL, testInfo);
    const d = await waitingDelivery(seed, { rice: 4, beans: 2 });

    await page.goto(`/warehouse/receive?order=${d.order.id}`);
    await chooseLocation(page, d.shelf.name);
    await page
      .getByRole("button", { name: "Receive one product at a time" })
      .click();
    const dialog = session(page);
    // The rice is the first card; the beans are in the worker's hand.
    await expect(
      dialog.getByRole("region", { name: d.rice.name }),
    ).toBeVisible();

    await dialog.getByRole("button", { name: "Scan", exact: true }).click();
    await expect(page.locator("#qr-reader video")).toBeVisible({
      timeout: 15000,
    });
    await camera.showEan13(d.beans.barcode);
    await expect(
      dialog.getByRole("region", { name: d.beans.name }),
    ).toBeVisible({
      timeout: 20000,
    });
    await expect(dialog.getByText("Scanned", { exact: true })).toBeVisible();

    // Closing the camera lets the phone have it back.
    await dialog.getByRole("button", { name: "Close", pressed: true }).click();
    await expect(page.locator("#qr-reader video")).toHaveCount(0);
    await expect.poll(async () => (await camera.streams()).live).toBe(0);
  });

  test("the camera on the receive screen adds the product it reads", async ({
    page,
    camera,
    playwright,
    baseURL,
  }, testInfo) => {
    const seed = await startSeed({ playwright }, baseURL, testInfo);
    const shelf = await seed.shelf("Shelf");
    const supplier = await seed.partner("Supplier", "SUPPLIER");
    const rice = await seed.product("Rice");

    await page.goto("/warehouse/receive");
    await choosePartner(page, supplier.name);
    await chooseLocation(page, shelf.name);
    await page.getByRole("button", { name: "Scan", exact: true }).click();
    await expect(page.locator("#qr-reader video")).toBeVisible({
      timeout: 15000,
    });
    await camera.showEan13(rice.barcode);
    await expect(
      page.getByRole("spinbutton", { name: `How many arrived: ${rice.name}` }),
    ).toHaveValue("1", { timeout: 20000 });
  });

  test("a line put elsewhere is booked on the shelf that was scanned", async ({
    page,
    playwright,
    baseURL,
    authenticatedPage: _auth,
  }, testInfo) => {
    const seed = await startSeed({ playwright }, baseURL, testInfo);
    const d = await waitingDelivery(seed, { rice: 3, beans: 2 });
    const other = await seed.shelf("OtherShelf");

    await page.goto(`/warehouse/receive?order=${d.order.id}`);
    await chooseLocation(page, d.shelf.name);
    await page
      .getByRole("button", { name: "Receive one product at a time" })
      .click();
    const dialog = session(page);
    await expect(dialog.getByText(d.shelf.name, { exact: true })).toBeVisible();

    await dialog
      .getByRole("button", { name: "I'm putting it elsewhere" })
      .click();
    await expect(
      dialog.getByText("Choose the location, or scan its label."),
    ).toBeVisible();
    const label = dialog.getByRole("textbox", {
      name: "Scan the location label",
    });
    await label.fill(other.code);
    await label.press("Enter");
    await expect(dialog.getByText(other.name, { exact: true })).toBeVisible();
    await expect(dialog.getByText(d.shelf.name, { exact: true })).toHaveCount(
      0,
    );

    await scanShelf(page, other.code);
    await dialog.getByRole("button", { name: "Correct, next" }).click();

    // The beans were planned for the delivery's shelf, which nobody has
    // confirmed yet: the card asks for it, and the rice's shelf is no answer.
    await expect(
      dialog.getByText("Scan the location to confirm"),
    ).toBeVisible();
    await scanShelf(page, d.shelf.code);
    await dialog
      .getByRole("button", { name: "Correct, finish receiving" })
      .click();
    await expect(
      dialog.getByRole("heading", { name: "Received 2 lines" }),
    ).toBeVisible({ timeout: 15000 });

    // Each line lies on the shelf its own scan named.
    expect(await seed.onHand(d.rice, other)).toBe(3);
    expect(await seed.onHand(d.rice, d.shelf)).toBe(0);
    expect(await seed.onHand(d.beans, d.shelf)).toBe(2);
    expect(await seed.onHand(d.beans, other)).toBe(0);
  });

  // The same walk, but "Receive more" is pressed on the answer instead of the
  // screen being opened afresh: the receipt is built from the order as it
  // stands after the first delivery, so only the line still owed is offered.
  test("Receive more after a partial delivery offers only what is still owed", async ({
    page,
    playwright,
    baseURL,
    authenticatedPage: _auth,
  }, testInfo) => {
    const seed = await startSeed({ playwright }, baseURL, testInfo);
    const d = await waitingDelivery(seed);

    await openFromStart(page);
    await choosePartner(page, d.supplier.name);
    await openSession(page, d.supplier.name, d.shelf.name);
    await countField(page, d.rice.name).fill("6");
    await scanShelf(page, d.shelf.code);
    await session(page).getByRole("button", { name: "Correct, next" }).click();
    await session(page)
      .getByRole("button", { name: "Correct, finish receiving" })
      .click();
    await expect(
      session(page).getByRole("heading", { name: "Received 2 lines" }),
    ).toBeVisible({ timeout: 15000 });

    await session(page).getByRole("button", { name: "Receive more" }).click();
    await choosePartner(page, d.supplier.name);
    await expect(
      page.getByText(`${d.order.number} expects 1 line.`),
    ).toBeVisible();
    await openSession(page, d.supplier.name, d.shelf.name);
    await expect(
      session(page).getByText("0 of 1", { exact: true }),
    ).toBeVisible();
    await expect(session(page).getByText("Still due 4 pcs.")).toBeVisible();
  });
});
