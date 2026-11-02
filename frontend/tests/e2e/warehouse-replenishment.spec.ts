import {
  type APIRequestContext,
  type Locator,
  type Page,
} from "@playwright/test";
import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { showMoreUntilVisible } from "./helpers/todo-list";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * Filling a pick face from the reserve rack, walked on the screens.
 *
 * A reorder rule watches the pick face. Once the rack beside it is marked as
 * reserve, the alert stops asking to buy what the rack already holds and
 * offers to carry it: the same offer is a task on Start and a card on the
 * Board, and one press posts the transfer. Every test reads the stock and the
 * alert afterwards through the API: the promise is a full shelf and a
 * cleared alert, so a green toast over an unmoved shelf must not pass.
 *
 * The part that needs an approval workflow or the shelf-scan rule changes
 * organisation-wide state and lives in `warehouse-replenishment-approvals`.
 */

// The largest page: the default is 50 and the shared database may hold more
// alerts than that, so the rule's own could sit on a page that is never read.
const ALERTS = "/api/v1/purchase-orders/replenishment/alerts?limit=200";

const MIN = 10;
const MAX = 20;
const ON_PICK_FACE = 3;
const ON_RESERVE = 40;
const TO_CARRY = MAX - ON_PICK_FACE;

interface Alert {
  reorder_rule_id: string;
  product_name: string;
  available_quantity: number;
  reserve_available_quantity: number;
  proposed_move_quantity: number;
  remaining_to_buy: number;
}

interface Seeded {
  uid: string;
  productName: string;
  pickName: string;
  reserveName: string;
  pickId: string;
  reserveId: string;
  templateId: string;
  ruleId: string;
}

test.describe("Warehouse — replenishing a pick face from reserve", () => {
  let ctx: APIRequestContext;
  let api: ApiHelper;
  let token: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
    await api.enableAllModules(token);
  });

  const auth = () => ({ Authorization: `Bearer ${token}` });
  const rules: string[] = [];

  // A rule left behind keeps raising an alert on Start and on the reorder
  // screen for every spec that opens them after this one.
  test.afterAll(async () => {
    for (const id of rules) {
      await ctx
        .delete(`/api/v1/purchase-orders/reorder-rules/${id}`, {
          headers: auth(),
        })
        .catch(() => {});
    }
  });

  /**
   * A warehouse with a pick face short of its minimum and a rack holding the
   * rest. The rack is not marked as reserve yet: that is the first step of
   * the walk.
   */
  async function seed(workerIndex: number): Promise<Seeded> {
    const uid = `${Date.now().toString(36)}-w${workerIndex}-${Math.random()
      .toString(36)
      .slice(2, 6)}`;
    const warehouse = await api.createStorage(token, {
      name: `E2E-Replen-WH-${uid}`,
    });
    const pickName = `E2E-Replen-Pick-${uid}`;
    const reserveName = `E2E-Replen-Rack-${uid}`;
    const pick = await api.createStorage(token, {
      name: pickName,
      parent_id: warehouse.id,
    });
    const reserve = await api.createStorage(token, {
      name: reserveName,
      parent_id: warehouse.id,
    });
    const productName = `E2E-Replen-Rice-${uid}`;
    const template = await api.createProductTemplate(token, {
      name: productName,
    });
    await api.createItemForTemplate(token, {
      name: productName,
      template_id: template.id,
      location_id: pick.id,
      quantity: ON_PICK_FACE,
    });
    await api.createItemForTemplate(token, {
      name: productName,
      template_id: template.id,
      location_id: reserve.id,
      quantity: ON_RESERVE,
    });
    const rule = await ctx.post("/api/v1/purchase-orders/reorder-rules", {
      headers: auth(),
      data: {
        product_template_id: template.id,
        location_id: pick.id,
        min_quantity: MIN,
        max_quantity: MAX,
      },
    });
    expect(rule.ok(), await rule.text()).toBe(true);
    const ruleId = (await rule.json()).id as string;
    rules.push(ruleId);
    return {
      uid,
      productName,
      pickName,
      reserveName,
      pickId: pick.id,
      reserveId: reserve.id,
      templateId: template.id,
      ruleId,
    };
  }

  async function alertOf(s: Seeded): Promise<Alert | undefined> {
    const response = await ctx.get(ALERTS, { headers: auth() });
    expect(response.ok(), await response.text()).toBe(true);
    return ((await response.json()) as { items: Alert[] }).items.find(
      (a) => a.reorder_rule_id === s.ruleId,
    );
  }

  /**
   * The replenishment task for the rule, read from the server's own list: the
   * lists on Start and the Board are cut to a hundred and the shared database
   * may hold more, so "not on screen" would pass for the wrong reason.
   */
  async function taskOf(s: Seeded): Promise<unknown> {
    const today = new Date().toISOString().slice(0, 10);
    const response = await ctx.get(
      `/api/v1/warehouse/todo?date_to=${today}&limit=1&work_limit=1000`,
      { headers: auth() },
    );
    expect(response.ok(), await response.text()).toBe(true);
    const items = (await response.json()).work_items.items as Array<{
      source_kind: string;
      source_id: string;
    }>;
    return items.find(
      (i) => i.source_kind === "replenishment" && i.source_id === s.ruleId,
    );
  }

  /** The Locations screen: tick "Reserve location" on the rack and save. */
  async function markAsReserve(page: Page, s: Seeded) {
    await page.goto(`/inventory/locations/${s.reserveId}`);
    await expect(
      page.getByRole("heading", { level: 2, name: s.reserveName }),
    ).toBeVisible({ timeout: 15000 });
    await page.getByRole("tab", { name: "Settings" }).click();
    const reserve = page.getByRole("checkbox", { name: "Reserve location" });
    await expect(reserve).not.toBeChecked();
    await reserve.check();
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect
      .poll(
        async () => {
          const read = await ctx.get(`/api/v1/locations/${s.reserveId}`, {
            headers: auth(),
          });
          return (await read.json()).settings?.is_reserve === true;
        },
        { timeout: 15000 },
      )
      .toBe(true);
  }

  /**
   * Whether the organisation asks for the reserve shelf to be scanned before
   * goods leave it. The warehouse profile is shared by every spec and the
   * Configuration spec flips this switch, so the walk follows whatever it is:
   * the sheet asks for the scan, or it does not, and the post goes through
   * either way. `warehouse-replenishment-approvals` pins both states.
   */
  async function postTheMove(sheet: Locator, reserveId: string): Promise<void> {
    const profile = await ctx.get("/api/v1/warehouse/profile", {
      headers: auth(),
    });
    const asksForScan = (await profile.json()).confirm_shelf_by_scan === true;
    const scan = sheet.getByRole("textbox", {
      name: "Scan the reserve location",
    });
    if (asksForScan) {
      const rack = await ctx.get(`/api/v1/locations/${reserveId}`, {
        headers: auth(),
      });
      await scan.fill((await rack.json()).short_code);
    } else {
      await expect(scan).toHaveCount(0);
    }
    await sheet.getByRole("button", { name: "Post the move" }).click();
  }

  const carrySentence = (s: Seeded) =>
    new RegExp(
      `Carry ${TO_CARRY}.* ${s.productName} from reserve to ${s.pickName}`,
    );

  test("marking the rack as reserve turns the buy alert into a carry, and posting it fills the shelf", async ({
    page,
    authenticatedPage,
  }, testInfo) => {
    // Seven screens from the alert to the posted move: past the default
    // 30 s on a loaded machine.
    test.setTimeout(90_000);
    void authenticatedPage;
    const s = await seed(testInfo.workerIndex);

    // Before the rack is marked, nothing in the warehouse is reserve: the
    // whole shortage is a purchase and there is nothing to carry.
    const before = await alertOf(s);
    expect(before?.reserve_available_quantity).toBe(0);
    expect(before?.proposed_move_quantity).toBe(0);
    expect(before?.remaining_to_buy).toBe(TO_CARRY);

    await markAsReserve(page, s);

    // The alert now says the rack covers the shortage.
    const after = await alertOf(s);
    expect(after?.reserve_available_quantity).toBe(ON_RESERVE);
    expect(after?.proposed_move_quantity).toBe(TO_CARRY);
    expect(after?.remaining_to_buy).toBe(0);

    // The reorder screen shows it, in words a buyer reads: reserve holds the
    // goods, nothing is left to buy.
    await page.goto("/purchase-orders/reorder-rules");
    const alertRow = page
      .getByRole("listitem")
      .filter({ hasText: s.productName });
    await expect(alertRow).toContainText(`Reserve holds ${ON_RESERVE}`);
    await expect(alertRow).toContainText("Reserve covers the whole shortage");

    // The same offer is a task on Start …
    expect(await taskOf(s)).toBeTruthy();
    await page.goto("/warehouse/todo");
    await showMoreUntilVisible(page, page.getByText(carrySentence(s)));

    // … and a card on the Board, in the To do column, kind "Replenish".
    await page.goto("/warehouse/board");
    const todoColumn = page.getByRole("region", { name: "To do" });
    const card = todoColumn.getByText(carrySentence(s));
    await showMoreUntilVisible(page, card);
    await expect(
      todoColumn
        .getByRole("article")
        .filter({ hasText: s.productName })
        .getByText("Replenish", { exact: true }),
    ).toBeVisible();

    // "Replenish" on the alert opens the prepared transfer on Start.
    await page.goto("/purchase-orders/reorder-rules");
    await page
      .getByRole("listitem")
      .filter({ hasText: s.productName })
      .getByRole("button", { name: "Replenish" })
      .click();
    const sheet = page.getByRole("dialog", { name: "Replenish from reserve" });
    await showMoreUntilVisible(page, sheet);
    await expect(page).toHaveURL(/\/warehouse\/todo/);
    await expect(sheet).toContainText(`From ${s.reserveName}`);
    await expect(sheet).toContainText(`To ${s.pickName}`);
    await expect(sheet).toContainText(s.productName);

    await postTheMove(sheet, s.reserveId);
    await expect(page.getByText(/Replenished — .* posted/)).toBeVisible({
      timeout: 15000,
    });
    await expect(sheet).toBeHidden();

    // The ledger moved by exactly the proposal, the shelf reached its maximum
    // and the rack lost what it gave.
    await expect
      .poll(() => api.quantityOnHand(token, s.templateId, s.pickId), {
        timeout: 15000,
      })
      .toBe(MAX);
    expect(await api.quantityOnHand(token, s.templateId, s.reserveId)).toBe(
      ON_RESERVE - TO_CARRY,
    );

    // The alert and the task are gone, and the task does not come back on a
    // fresh read of Start.
    expect(await alertOf(s)).toBeUndefined();
    expect(await taskOf(s)).toBeUndefined();
    await page.goto("/warehouse/todo");
    await expect(page.getByRole("heading", { name: "What are we doing?" })).toBeVisible();
    await expect(page.getByText(carrySentence(s))).toHaveCount(0);
  });

  test("a proposal that went stale while the sheet was open moves nothing and says why", async ({
    page,
    authenticatedPage,
  }, testInfo) => {
    void authenticatedPage;
    const s = await seed(testInfo.workerIndex);
    await markAsReserve(page, s);

    await page.goto(`/warehouse/todo?replenish=${s.ruleId}`);
    const sheet = page.getByRole("dialog", { name: "Replenish from reserve" });
    await showMoreUntilVisible(page, sheet);
    await expect(sheet).toContainText(s.productName);

    // Somebody else fills the shelf while the sheet is open.
    await api.createItemForTemplate(token, {
      name: s.productName,
      template_id: s.templateId,
      location_id: s.pickId,
      quantity: TO_CARRY,
    });
    await expect
      .poll(() => api.quantityOnHand(token, s.templateId, s.pickId), {
        timeout: 15000,
      })
      .toBe(MAX);

    await postTheMove(sheet, s.reserveId);
    await expect(
      page.getByText(/nothing to carry from reserve/i).first(),
    ).toBeVisible({ timeout: 15000 });

    // The refusal posted nothing: the rack still holds all it held.
    expect(await api.quantityOnHand(token, s.templateId, s.reserveId)).toBe(
      ON_RESERVE,
    );
    expect(await api.quantityOnHand(token, s.templateId, s.pickId)).toBe(MAX);
  });
});
