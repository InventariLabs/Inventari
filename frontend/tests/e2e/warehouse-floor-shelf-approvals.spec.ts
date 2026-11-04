import {
  type APIRequestContext,
  type Locator,
  type Page,
} from "@playwright/test";
import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * The shelf card on a phone: the code large as it is printed on the label,
 * the name under it and why that shelf. Receiving, the pick walk and a
 * put-away task read the same card, so the same words and the same order
 * (the shelf first, then the product) are checked on each, and every walk
 * ends at the stock ledger: the goods stand on the shelf the card named.
 *
 * Whether a session asks for the shelf's label before the product is the
 * warehouse profile's setting, and it is organization-wide: while a test here
 * turns it on, every picking and receiving session of every other spec would
 * start asking for labels. So this file lives in the single-worker project
 * that runs after the rest, sets the setting itself before each group and
 * puts it back afterwards.
 */

test.use({
  viewport: { width: 390, height: 844 },
  hasTouch: true,
  isMobile: true,
});

interface Shelf {
  id: string;
  name: string;
  code: string;
}

interface Product {
  id: string;
  name: string;
  barcode: string;
}

const RUN = Date.now().toString(36);
let sequence = 0;

/** A name no other test of this run, in this or another worker, shares. */
function unique(workerIndex: number, label: string): string {
  return `E2E-Shelf-${label}-${RUN}-w${workerIndex}-${sequence++}`;
}

/** Twelve digits, unique per call: the template's barcode must not collide. */
function barcode(): string {
  return `77${(Date.now() + sequence++).toString().slice(-10)}`;
}

class Floor {
  constructor(
    readonly ctx: APIRequestContext,
    readonly api: ApiHelper,
    readonly token: string,
    private readonly workerIndex: number,
  ) {}

  private headers() {
    return { Authorization: `Bearer ${this.token}` };
  }

  name(label: string): string {
    return unique(this.workerIndex, label);
  }

  async warehouse(label: string): Promise<{ id: string; name: string }> {
    const name = this.name(label);
    const made = await this.api.createStorage(this.token, { name });
    return { id: made.id, name };
  }

  async shelf(parentId: string, label: string): Promise<Shelf> {
    const name = this.name(label);
    const made = await this.api.createStorage(this.token, {
      name,
      parent_id: parentId,
      location_type: "SHELF",
    });
    const read = await this.ctx.get(`/api/v1/locations/${made.id}`, {
      headers: this.headers(),
    });
    return { id: made.id, name, code: (await read.json()).short_code };
  }

  async product(label: string): Promise<Product> {
    const name = this.name(label);
    const code = barcode();
    const template = await this.api.createProductTemplate(this.token, {
      name,
      barcode: code,
    });
    return { id: template.id, name, barcode: code };
  }

  /** Stock of `product` standing on `shelf`, as an item the picker can take. */
  async stock(product: Product, shelf: Shelf, quantity: number) {
    return this.api.createItemForTemplate(this.token, {
      name: product.name,
      template_id: product.id,
      location_id: shelf.id,
      quantity,
    });
  }

  async onHand(product: Product, shelf: Shelf): Promise<number> {
    return this.api.quantityOnHand(this.token, product.id, shelf.id);
  }

  async supplier(): Promise<string> {
    const partner = await this.api.createPartner(this.token, {
      name: this.name("Supplier"),
      type: "SUPPLIER",
    });
    return partner.id;
  }

  async customer(): Promise<string> {
    const partner = await this.api.createPartner(this.token, {
      name: this.name("Customer"),
      type: "CUSTOMER",
    });
    return partner.id;
  }

  /** Receive into the warehouse's receiving area, to be put away later. */
  async twoStepReceiving(warehouseId: string) {
    const put = await this.ctx.put(
      `/api/v1/warehouse/putaway/receiving-modes/${warehouseId}`,
      { headers: this.headers(), data: { two_step: true } },
    );
    if (!put.ok()) {
      throw new Error(`Could not set two-step receiving: ${await put.text()}`);
    }
  }

  /** One completed delivery into the warehouse: the goods wait in its receiving area. */
  async deliverToReceivingArea(
    warehouseId: string,
    products: Product[],
    quantity: number,
  ) {
    const doc = await this.api.createDocument(this.token, {
      type: "IN",
      partner_id: await this.supplier(),
      target_location_id: warehouseId,
      lines: products.map((product) => ({
        product_template_id: product.id,
        expected_quantity: quantity,
      })),
    });
    await this.api.confirmDocument(this.token, doc.id);
    await this.api.completeDocument(this.token, doc.id);
  }

  /**
   * Put away every task waiting anywhere. The walk below carries the tasks of
   * the list one after another, in the list's order, and a task another spec
   * (or an earlier run) left in some other warehouse would sit between the two
   * this test made.
   */
  async clearPutawayTasks() {
    const parking = await this.api.createStorage(this.token, {
      name: this.name("Parking"),
    });
    for (let round = 0; round < 3; round++) {
      const read = await this.ctx.get(
        "/api/v1/warehouse/todo?limit=200&date_to=2999-12-31",
        { headers: this.headers() },
      );
      const tasks = ((await read.json()).work_items.items ?? []).filter(
        (task: { next_action: string }) => task.next_action === "put_away",
      ) as Array<{ source_id: string; place_id: string | null }>;
      if (tasks.length === 0) return;
      for (const task of tasks) {
        await this.ctx.post(
          `/api/v1/warehouse/work-items/putaway/${task.source_id}`,
          {
            headers: this.headers(),
            data: { location_id: task.place_id ?? parking.id },
          },
        );
      }
    }
  }

  /** The id the put-away call takes for the task of `product`. */
  async putawayLineId(product: Product): Promise<string> {
    const read = await this.ctx.get(
      "/api/v1/warehouse/todo?limit=200&date_to=2999-12-31",
      { headers: this.headers() },
    );
    const tasks = (await read.json()).work_items.items as Array<{
      next_action: string;
      subject: string;
      source_id: string;
    }>;
    const task = tasks.find(
      (entry) =>
        entry.next_action === "put_away" && entry.subject === product.name,
    );
    if (!task) throw new Error(`No put-away task for ${product.name}`);
    return task.source_id;
  }

  /** Whether sessions ask for the shelf's label first; returns what it was. */
  async askForShelfScan(on: boolean): Promise<boolean> {
    const read = await this.ctx.get("/api/v1/warehouse/profile", {
      headers: this.headers(),
    });
    const was = (await read.json()).confirm_shelf_by_scan === true;
    const put = await this.ctx.put("/api/v1/warehouse/profile", {
      headers: this.headers(),
      data: { confirm_shelf_by_scan: on },
    });
    if (!put.ok()) {
      throw new Error(`Could not set the shelf scan: ${await put.text()}`);
    }
    return was;
  }
}

/**
 * The put-away sheet's own choice of shelf: the picker searches the server,
 * so the shelf is typed and picked from what the search answers.
 */
async function chooseShelf(sheet: Locator, shelf: Shelf) {
  await sheet.getByRole("button", { name: "Choose a location" }).click();
  await sheet.getByRole("combobox", { name: "Line location" }).click();
  const page = sheet.page();
  await page.getByPlaceholder("Search locations").fill(shelf.name);
  // An answer is named by the shelf and, under it, the way to it.
  await page.getByRole("button", { name: shelf.name }).first().click();
}

/** What a hardware scanner does: the keys a few ms apart, then Enter. */
async function scan(page: Page, code: string) {
  await page.evaluate(() => (document.activeElement as HTMLElement)?.blur());
  await page.keyboard.type(code, { delay: 10 });
  await page.keyboard.press("Enter");
}

async function floorSetup(
  playwright: {
    request: { newContext: (o: object) => Promise<APIRequestContext> };
  },
  baseURL: string | undefined,
  workerIndex: number,
) {
  const ctx = await playwright.request.newContext({ baseURL });
  const api = new ApiHelper(ctx);
  const token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
  await api.completeOnboarding(token);
  await api.enableAllModules(token);
  // A workflow left by another spec would hold the posts below for approval.
  await api.cleanupApprovals(token);
  return new Floor(ctx, api, token, workerIndex);
}

test.describe("Floor shelf card — receiving", () => {
  test.describe.configure({ mode: "serial" });
  let floor: Floor;
  let askedBefore: boolean;

  test.beforeAll(async ({ playwright, baseURL }, testInfo) => {
    floor = await floorSetup(playwright, baseURL, testInfo.workerIndex);
  });
  test.afterAll(async () => {
    await floor.askForShelfScan(askedBefore);
  });

  /** A confirmed delivery of one product to a shelf, opened on the scan sheet. */
  async function openDelivery(
    page: Page,
    shelf: Shelf,
    product: Product,
    quantity: number,
  ) {
    const doc = await floor.api.createDocument(floor.token, {
      type: "IN",
      partner_id: await floor.supplier(),
      target_location_id: shelf.id,
      lines: [{ product_template_id: product.id, expected_quantity: quantity }],
    });
    await floor.api.confirmDocument(floor.token, doc.id);
    await page.goto(`/warehouse/documents/${doc.id}`);
    await page.getByRole("button", { name: "Scan receiving" }).click();
    await expect(page.getByText("Saves as you go")).toBeVisible();
  }

  test("the card names the shelf, and the scanned product is received onto it", async ({
    page,
    authenticatedPage,
  }) => {
    askedBefore = await floor.askForShelfScan(false);
    const warehouse = await floor.warehouse("Receiving-WH");
    const shelf = await floor.shelf(warehouse.id, "Receiving-A");
    const product = await floor.product("Rice");
    await openDelivery(page, shelf, product, 3);

    // The code as printed on the label is the large line; the name is under
    // it, then why this shelf. Nothing asks for a scan: the setting is off.
    const card = page.getByRole("region", { name: product.name });
    await expect(card.getByText("Put on", { exact: true })).toBeVisible();
    await expect(card.getByText(shelf.code, { exact: true })).toBeVisible();
    await expect(card.getByText(shelf.name, { exact: true })).toBeVisible();
    await expect(card.getByText("The delivery's location")).toBeVisible();
    await expect(card.getByText("Scan the location to confirm")).toHaveCount(0);

    await scan(page, product.barcode);
    await expect(card.getByText("Scanned", { exact: true })).toBeVisible();
    await page
      .getByRole("button", { name: "Correct, finish receiving" })
      .click();

    await expect
      .poll(() => floor.onHand(product, shelf), { timeout: 15000 })
      .toBe(3);
  });
  test("with the setting on the shelf is scanned first, and the product waits for it", async ({
    page,
    authenticatedPage,
  }) => {
    await floor.askForShelfScan(true);
    const warehouse = await floor.warehouse("Receiving-Gated-WH");
    const shelf = await floor.shelf(warehouse.id, "Receiving-Gated-A");
    const other = await floor.shelf(warehouse.id, "Receiving-Gated-B");
    const product = await floor.product("Beans");
    await openDelivery(page, shelf, product, 2);

    const card = page.getByRole("region", { name: product.name });
    await expect(card.getByText(shelf.code, { exact: true })).toBeVisible();
    await expect(card.getByText("Scan the location to confirm")).toBeVisible();

    // The product first. The scan only names the line; booking its count is
    // what the shelf has to precede, so finishing is refused in words that
    // name the shelf, and nothing reaches the ledger.
    await scan(page, product.barcode);
    await expect(card.getByText("Scanned", { exact: true })).toBeVisible();
    await page
      .getByRole("button", { name: "Correct, finish receiving" })
      .click();
    await expect(page.getByText(/Scan the location first: /)).toBeVisible();
    await expect(card.getByText("Scan the location to confirm")).toBeVisible();
    expect(await floor.onHand(product, shelf)).toBe(0);

    // Another shelf's label is not the one the card names.
    await scan(page, other.code);
    await expect(
      page.getByText(/That is not the location — go to /),
    ).toBeVisible();
    await expect(card.getByText("Scan the location to confirm")).toBeVisible();

    // The right label confirms the card, and now the same press books it.
    await scan(page, shelf.code);
    await expect(card.getByText("Location confirmed")).toBeVisible();
    expect(await floor.onHand(product, shelf)).toBe(0);
    await page
      .getByRole("button", { name: "Correct, finish receiving" })
      .click();
    await expect
      .poll(() => floor.onHand(product, shelf), { timeout: 15000 })
      .toBe(2);
    expect(await floor.onHand(product, other)).toBe(0);
  });
});

test.describe("Floor shelf card — picking", () => {
  test.describe.configure({ mode: "serial" });
  let floor: Floor;
  let askedBefore: boolean;

  test.beforeAll(async ({ playwright, baseURL }, testInfo) => {
    floor = await floorSetup(playwright, baseURL, testInfo.workerIndex);
  });
  test.afterAll(async () => {
    await floor.askForShelfScan(askedBefore);
  });

  /** A confirmed dispatch of one unit per product, each taken from its shelf. */
  async function openDispatch(
    page: Page,
    warehouseId: string,
    lines: Array<{ product: Product; shelf: Shelf }>,
  ) {
    const items = [];
    for (const { product, shelf } of lines) {
      items.push(await floor.stock(product, shelf, 5));
    }
    const doc = await floor.api.createDocument(floor.token, {
      type: "OUT",
      partner_id: await floor.customer(),
      source_location_id: warehouseId,
      lines: lines.map(({ product }, index) => ({
        item_id: items[index].id,
        product_template_id: product.id,
        expected_quantity: 1,
      })),
    });
    await floor.api.confirmDocument(floor.token, doc.id);
    await page.goto(`/warehouse/documents/${doc.id}`);
    await page.getByRole("button", { name: "Scan picking" }).click();
    return {
      docId: doc.id,
      sheet: page.getByRole("dialog", { name: "Picking" }),
    };
  }

  async function lineStates(docId: string): Promise<string[]> {
    const doc = (await floor.api.getDocument(
      floor.token,
      docId,
    )) as unknown as {
      lines: Array<{ line_status: string }>;
    };
    return doc.lines.map((line) => line.line_status);
  }

  test("the card leads with the shelf, and the picked session ends in a summary", async ({
    page,
    authenticatedPage,
  }) => {
    askedBefore = await floor.askForShelfScan(false);
    const warehouse = await floor.warehouse("Picking-WH");
    const shelf = await floor.shelf(warehouse.id, "Picking-A");
    const product = await floor.product("Flour");
    const { docId, sheet } = await openDispatch(page, warehouse.id, [
      { product, shelf },
    ]);

    await expect(sheet.getByText("Take from", { exact: true })).toBeVisible();
    await expect(sheet.getByText(shelf.code, { exact: true })).toBeVisible();
    await expect(sheet.getByText(shelf.name, { exact: true })).toBeVisible();
    await expect(sheet.getByText("Scan the location label")).toHaveCount(0);

    await scan(page, product.barcode);
    await expect(page.locator("body")).toContainText("Picking complete");
    await expect(sheet.getByText("1 of 1 lines picked")).toBeVisible();
    await expect(sheet.getByText("1 picked", { exact: true })).toBeVisible();
    await expect(
      sheet.getByRole("button", { name: "Scan tracking number" }),
    ).toBeVisible();
    await sheet.getByRole("button", { name: "Complete and book" }).click();

    // The pick is on the document: the line is done and the unit it took is
    // still held on the shelf the card named, until the order ships.
    await expect.poll(() => lineStates(docId)).toEqual(["DONE"]);
    const [quant] = await floor.api.listQuants(
      floor.token,
      product.id,
      shelf.id,
    );
    expect(Number(quant.reserved_quantity)).toBe(1);
  });
  test("with the setting on each shelf is scanned before its product, line after line", async ({
    page,
    authenticatedPage,
  }) => {
    await floor.askForShelfScan(true);
    const warehouse = await floor.warehouse("Picking-Gated-WH");
    const first = await floor.shelf(warehouse.id, "Picking-Gated-A");
    const second = await floor.shelf(warehouse.id, "Picking-Gated-B");
    const flour = await floor.product("Flour");
    const sugar = await floor.product("Sugar");
    const { docId, sheet } = await openDispatch(page, warehouse.id, [
      { product: flour, shelf: first },
      { product: sugar, shelf: second },
    ]);

    // The card is the block above the lines: "Take from", the shelf's code,
    // its name and whether the label is still to be scanned. Which line is in
    // hand is the server's walk order, so each step reads the shelf the card
    // names and acts on that one.
    const card = sheet.getByText("Take from", { exact: true }).locator("..");
    let remaining = [
      { shelf: first, product: flour },
      { shelf: second, product: sugar },
    ];
    const visited: string[] = [];
    for (let picked = 0; picked < 2; picked++) {
      await expect(card).toContainText(
        new RegExp(remaining.map(({ shelf }) => shelf.code).join("|")),
      );
      const text = await card.innerText();
      const step = remaining.find(({ shelf }) => text.includes(shelf.code))!;
      visited.push(step.shelf.code);
      remaining = remaining.filter((entry) => entry !== step);
      const progress = sheet.getByText(`${picked}/2 picked`);

      await expect(card.getByText("Scan the location label")).toBeVisible();
      await expect(card).toContainText(step.shelf.name);

      // The product before its shelf: refused, and nothing is picked.
      await scan(page, step.product.barcode);
      await expect(
        page.getByText(/Scan the location first: /).first(),
      ).toBeVisible();
      await expect(progress).toBeVisible();
      await expect(card.getByText("Scan the location label")).toBeVisible();

      // The shelf, then the product on it.
      await scan(page, step.shelf.code);
      await expect(card.getByText("Location confirmed")).toBeVisible();
      await scan(page, step.product.barcode);
      // The last pick ends the session, which is the summary's to say.
      if (picked === 0) {
        await expect(sheet.getByText("1/2 picked")).toBeVisible();
      }
    }
    // Two different shelves, each asked for in its turn.
    expect(visited.sort()).toEqual([first.code, second.code].sort());

    await expect(sheet.getByText("Picking complete")).toBeVisible();
    await expect(sheet.getByText("2 of 2 lines picked")).toBeVisible();
    await sheet.getByRole("button", { name: "Complete and book" }).click();
    await expect.poll(() => lineStates(docId)).toEqual(["DONE", "DONE"]);
  });
});

test.describe("Floor shelf card — put-away tasks", () => {
  test.describe.configure({ mode: "serial" });
  let floor: Floor;
  let askedBefore: boolean;

  test.beforeAll(async ({ playwright, baseURL }, testInfo) => {
    floor = await floorSetup(playwright, baseURL, testInfo.workerIndex);
    askedBefore = await floor.askForShelfScan(false);
    await floor.clearPutawayTasks();
  });
  test.afterAll(async () => {
    await floor.askForShelfScan(askedBefore);
  });

  /**
   * The Start screen with the put-away tasks of `products` on it, the one that
   * comes first in the list opened; which one that is, is the list's order
   * (the day, then the task's own key), not the order the goods were received
   * in. The list is the whole organization's work, a hundred rows at a time,
   * and a carry walks the tasks that are loaded, so the list is opened as far
   * as the last of them first. Returns the products in the order they come.
   */
  async function openFirstTask(
    page: Page,
    products: Product[],
  ): Promise<Product[]> {
    await page.goto("/warehouse/todo");
    const rowOf = (product: Product) =>
      page
        .getByText(product.name)
        .first()
        .locator(
          'xpath=ancestor::div[.//button[normalize-space(.)="Put away"]][1]',
        );
    const more = page.getByRole("button", { name: "Show more" });
    await expect(page.getByRole("region", { name: "Tasks" })).toBeVisible({
      timeout: 15000,
    });
    const allShown = async () => {
      for (const product of products) {
        if (!(await rowOf(product).isVisible())) return false;
      }
      return true;
    };
    for (let loaded = 0; loaded < 5; loaded++) {
      if ((await allShown()) || !(await more.isVisible())) break;
      await more.click();
    }
    for (const product of products) {
      await expect(rowOf(product)).toBeVisible({ timeout: 15000 });
    }
    const text = await page.getByRole("region", { name: "Tasks" }).innerText();
    const ordered = [...products].sort(
      (a, b) => text.indexOf(a.name) - text.indexOf(b.name),
    );
    await rowOf(ordered[0]).getByRole("button", { name: "Put away" }).click();
    return ordered;
  }

  async function leave(sheet: Locator) {
    if (await sheet.isVisible()) {
      await sheet.getByRole("button", { name: "Cancel" }).click();
    }
  }

  /**
   * Putting goods away on a shelf no rule named asks whether it is now the
   * product's home. None of the products here has a rule, so every post is
   * answered with the question; the carry walks on only once it is answered.
   */
  async function declineHomeShelf(page: Page) {
    const ask = page.getByRole("dialog", { name: "Home location" });
    await expect(ask).toBeVisible();
    await ask.getByRole("button", { name: "No", exact: true }).click();
    await expect(ask).toBeHidden();
  }

  test("a task no rule, stock or move offers a shelf for asks for one", async ({
    page,
    authenticatedPage,
  }) => {
    const warehouse = await floor.warehouse("Putaway-Cold-WH");
    const shelf = await floor.shelf(warehouse.id, "Putaway-Cold-A");
    await floor.twoStepReceiving(warehouse.id);
    const cold = await floor.product("Cold");
    await floor.deliverToReceivingArea(warehouse.id, [cold], 2);

    await openFirstTask(page, [cold]);
    const sheet = page.getByRole("dialog", { name: "Put away" });
    await expect(sheet.getByText(cold.name).first()).toBeVisible();

    // The block is the action that names a shelf, never the warehouse, and
    // the post waits for it.
    await expect(
      sheet.getByRole("button", { name: "Choose a location" }),
    ).toBeVisible();
    await expect(
      sheet.getByRole("button", { name: "Put away", exact: true }),
    ).toBeDisabled();
    await chooseShelf(sheet, shelf);
    await expect(sheet.getByText(shelf.code, { exact: true })).toBeVisible();
    await expect(sheet.getByText(shelf.name, { exact: true })).toBeVisible();
    await sheet.getByRole("button", { name: "Put away", exact: true }).click();

    await expect
      .poll(() => floor.onHand(cold, shelf), { timeout: 15000 })
      .toBe(2);
    await leave(sheet);
  });

  test("the carry walks task after task, and the offers follow the stock and the last move", async ({
    page,
    authenticatedPage,
  }) => {
    const warehouse = await floor.warehouse("Putaway-WH");
    const shelfA = await floor.shelf(warehouse.id, "Putaway-A");
    const shelfB = await floor.shelf(warehouse.id, "Putaway-B");
    await floor.twoStepReceiving(warehouse.id);
    const stocked = await floor.product("Stocked");
    const lastOne = await floor.product("Last-1");
    const lastTwo = await floor.product("Last-2");
    await floor.stock(stocked, shelfA, 4);
    await floor.deliverToReceivingArea(
      warehouse.id,
      [stocked, lastOne, lastTwo],
      2,
    );

    // The list orders same-day tasks by their own key, so which of the three
    // comes first differs from run to run. Whatever the order, the stocked
    // product is offered its shelf, and any other product that comes after
    // a move is offered the shelf that move used: both are always walked.
    const walk = await openFirstTask(page, [stocked, lastOne, lastTwo]);
    const sheet = page.getByRole("dialog", { name: "Put away" });
    const done = (button = "Put away") =>
      sheet.getByRole("button", { name: button, exact: true });

    // The shelf the last move into this warehouse used: none before the first.
    let lastUsed: Shelf | null = null;
    const offered = new Set<string>();
    for (const [step, product] of walk.entries()) {
      await expect(
        sheet.getByText(new RegExp(`Put away ${step + 1} of 3`)),
      ).toBeVisible();
      await expect(sheet.getByText(product.name).first()).toBeVisible();

      let target: Shelf;
      if (product === stocked) {
        // The product already lies on shelf A, whatever moved last.
        target = shelfA;
        offered.add("stock");
        await expect(
          sheet.getByText("The product already lies here"),
        ).toBeVisible();
      } else if (lastUsed) {
        // No stock of its own, but a move into this warehouse has been made.
        target = lastUsed;
        offered.add("last move");
        await expect(
          sheet.getByText("The location of the last move here"),
        ).toBeVisible();
      } else {
        // The first move of the warehouse: nothing to offer, so it is asked.
        // (Only the product that comes first can be in this case.)
        target = shelfB;
        await chooseShelf(sheet, target);
      }
      await expect(sheet.getByText(target.code, { exact: true })).toBeVisible();
      await expect(sheet.getByText(target.name, { exact: true })).toBeVisible();
      await done().click();
      await declineHomeShelf(page);
      lastUsed = target;
      await expect
        .poll(() => floor.onHand(product, target), { timeout: 15000 })
        .toBe(product === stocked ? 6 : 2);
    }
    await leave(sheet);
    expect([...offered].sort()).toEqual(["last move", "stock"]);

    // Stock stands where each card said, and nowhere else.
    expect(await floor.onHand(stocked, shelfA)).toBe(6);
    expect(await floor.onHand(stocked, shelfB)).toBe(0);
  });
  test("with the setting on a task is posted only once its shelf label is scanned", async ({
    page,
    authenticatedPage,
  }) => {
    await floor.askForShelfScan(true);
    const warehouse = await floor.warehouse("Putaway-Gated-WH");
    const shelfA = await floor.shelf(warehouse.id, "Putaway-Gated-A");
    const shelfB = await floor.shelf(warehouse.id, "Putaway-Gated-B");
    await floor.twoStepReceiving(warehouse.id);
    const first = await floor.product("Gated-1");
    const second = await floor.product("Gated-2");
    // Both already lie on shelf A, so both tasks name it.
    await floor.stock(first, shelfA, 1);
    await floor.stock(second, shelfA, 1);
    await floor.deliverToReceivingArea(warehouse.id, [first, second], 2);

    const walk = await openFirstTask(page, [first, second]);
    const sheet = page.getByRole("dialog", { name: "Put away" });
    const post = sheet.getByRole("button", { name: "Put away", exact: true });

    // The server holds the same rule: the screen is not what keeps it.
    const lineId = await floor.putawayLineId(walk[0]);
    const refused = await floor.ctx.post(
      `/api/v1/warehouse/work-items/putaway/${lineId}`,
      {
        headers: { Authorization: `Bearer ${floor.token}` },
        data: { location_id: shelfA.id },
      },
    );
    expect(refused.ok()).toBe(false);

    for (const [step, product] of walk.entries()) {
      await expect(
        sheet.getByText(new RegExp(`Put away ${step + 1} of 2`)),
      ).toBeVisible();
      await expect(sheet.getByText(product.name).first()).toBeVisible();
      await expect(sheet.getByText(shelfA.code, { exact: true })).toBeVisible();
      await expect(
        sheet.getByText("Scan the location to confirm"),
      ).toBeVisible();
      await expect(post).toBeDisabled();

      // Another shelf's label is not the one the card names.
      await scan(page, shelfB.code);
      await expect(
        page.getByText(/That is not the location — go to /),
      ).toBeVisible();
      await expect(post).toBeDisabled();

      // The right label confirms the card and releases the button.
      await scan(page, shelfA.code);
      await expect(sheet.getByText("Location confirmed")).toBeVisible();
      await expect(post).toBeEnabled();
      expect(await floor.onHand(product, shelfA)).toBe(1);
      await post.click();
      await declineHomeShelf(page);
      await expect
        .poll(() => floor.onHand(product, shelfA), { timeout: 15000 })
        .toBe(3);
    }
    await leave(sheet);
  });
});
