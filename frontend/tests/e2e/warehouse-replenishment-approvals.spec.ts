import { type APIRequestContext, type Page } from "@playwright/test";
import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { showMoreUntilVisible } from "./helpers/todo-list";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * Filling a pick face from reserve under the two organisation-wide rules that
 * change what the press of "Post the move" does: the shelf scan the warehouse
 * profile can ask for, and an approval workflow that holds transfers.
 *
 * Both rewrite state every document spec shares (the warehouse profile, the
 * workflows of the organisation), so this file is named for the `approvals`
 * project, which runs alone and in one worker after the rest. It puts the
 * profile and the workflows back in `afterAll`.
 */

// The largest page: the default is 50 and the shared database may hold more
// alerts than that, so the rule's own could sit on a page that is never read.
const ALERTS = "/api/v1/purchase-orders/replenishment/alerts?limit=200";
const PROPOSALS = "/api/v1/purchase-orders/replenishment/proposals";
const DRAFT_POS = "/api/v1/purchase-orders/replenishment/draft-pos";

const MIN = 10;
const MAX = 20;
const ON_PICK_FACE = 3;
const ON_RESERVE = 40;
const TO_CARRY = MAX - ON_PICK_FACE;

type Profile = Record<string, unknown>;

interface Alert {
  reorder_rule_id: string;
}

interface Seeded {
  productName: string;
  pickName: string;
  reserveName: string;
  reserveCode: string;
  pickId: string;
  reserveId: string;
  templateId: string;
  ruleId: string;
}

test.describe("Warehouse — replenishing from reserve under organisation rules", () => {
  test.describe.configure({ mode: "serial" });

  let ctx: APIRequestContext;
  let api: ApiHelper;
  let token: string;
  let original: Profile;
  const rules: string[] = [];
  const workflows: string[] = [];

  const auth = () => ({ Authorization: `Bearer ${token}` });

  test.beforeAll(async ({ playwright, baseURL }) => {
    ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
    await api.enableAllModules(token);
    // One user raises and decides in these tests; self-approval is an
    // organisation setting that is off by default.
    await api
      .setModuleSettings(token, "approvals", { allow_admin_self_approve: true })
      .catch(() => {});
    original = await readProfile();
  });

  test.afterAll(async () => {
    for (const id of workflows) await api.deleteWorkflow(token, id);
    for (const id of rules) {
      await ctx
        .delete(`/api/v1/purchase-orders/reorder-rules/${id}`, {
          headers: auth(),
        })
        .catch(() => {});
    }
    await writeProfile({
      confirm_shelf_by_scan: original.confirm_shelf_by_scan,
      approval_required_for_types: original.approval_required_for_types,
    });
  });

  async function readProfile(): Promise<Profile> {
    const response = await ctx.get("/api/v1/warehouse/profile", {
      headers: auth(),
    });
    expect(response.ok(), await response.text()).toBe(true);
    return (await response.json()) as Profile;
  }

  /** The profile is replaced whole; change only the fields named. */
  async function writeProfile(changes: Profile): Promise<void> {
    const current = await readProfile();
    const body = Object.fromEntries(
      Object.entries({ ...current, ...changes }).filter(
        ([key]) =>
          !["id", "organization_id", "created_at", "updated_at"].includes(key),
      ),
    );
    const response = await ctx.put("/api/v1/warehouse/profile", {
      headers: auth(),
      data: body,
    });
    expect(response.ok(), await response.text()).toBe(true);
  }

  /** A short pick face, a rack already marked as reserve, and the rule. */
  async function seed(workerIndex: number): Promise<Seeded> {
    const uid = `${Date.now().toString(36)}-w${workerIndex}-${Math.random()
      .toString(36)
      .slice(2, 6)}`;
    const warehouse = await api.createStorage(token, {
      name: `E2E-ReplenRule-WH-${uid}`,
    });
    const pickName = `E2E-ReplenRule-Pick-${uid}`;
    const reserveName = `E2E-ReplenRule-Rack-${uid}`;
    const pick = await api.createStorage(token, {
      name: pickName,
      parent_id: warehouse.id,
    });
    const reserve = (await api.createStorage(token, {
      name: reserveName,
      parent_id: warehouse.id,
      settings: { is_reserve: true },
    })) as { id: string; short_code?: string };
    const reserveRead = await ctx.get(`/api/v1/locations/${reserve.id}`, {
      headers: auth(),
    });
    const reserveCode = (await reserveRead.json()).short_code as string;
    expect(reserveCode).toBeTruthy();

    const productName = `E2E-ReplenRule-Rice-${uid}`;
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
      productName,
      pickName,
      reserveName,
      reserveCode,
      pickId: pick.id,
      reserveId: reserve.id,
      templateId: template.id,
      ruleId,
    };
  }

  async function hasAlert(s: Seeded): Promise<boolean> {
    const response = await ctx.get(ALERTS, { headers: auth() });
    expect(response.ok(), await response.text()).toBe(true);
    return ((await response.json()) as { items: Alert[] }).items.some(
      (a) => a.reorder_rule_id === s.ruleId,
    );
  }

  const onShelf = (s: Seeded, which: "pick" | "reserve") =>
    api.quantityOnHand(
      token,
      s.templateId,
      which === "pick" ? s.pickId : s.reserveId,
    );

  /** The task for the rule from the server's own list, not the cut one on screen. */
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

  const carrySentence = (s: Seeded) =>
    new RegExp(
      `Carry ${TO_CARRY}.* ${s.productName} from reserve to ${s.pickName}`,
    );

  async function openTheSheet(page: Page, s: Seeded) {
    await page.goto(`/warehouse/todo?replenish=${s.ruleId}`);
    const sheet = page.getByRole("dialog", { name: "Replenish from reserve" });
    await showMoreUntilVisible(page, sheet);
    await expect(sheet).toContainText(s.productName);
    return sheet;
  }

  test("when the profile asks for a scan, the reserve shelf is scanned before the goods leave it", async ({
    page,
    authenticatedPage,
  }, testInfo) => {
    void authenticatedPage;
    await writeProfile({ confirm_shelf_by_scan: true });
    const s = await seed(testInfo.workerIndex);
    const sheet = await openTheSheet(page, s);

    // Nothing to post until the shelf is scanned.
    const scan = sheet.getByRole("textbox", {
      name: "Scan the reserve location",
    });
    const post = sheet.getByRole("button", { name: "Post the move" });
    await expect(scan).toBeVisible();
    await expect(post).toBeDisabled();

    // A code that names another shelf is refused in words and moves nothing.
    await scan.fill(`NOT-${s.reserveCode}`);
    await post.click();
    await expect(
      page.getByText(/names another shelf|Scan the reserve location you are/i),
    ).toBeVisible({ timeout: 15000 });
    expect(await onShelf(s, "pick")).toBe(ON_PICK_FACE);
    expect(await onShelf(s, "reserve")).toBe(ON_RESERVE);

    // The right shelf posts it, and the shelf is full.
    await scan.fill(s.reserveCode);
    await post.click();
    await expect(page.getByText(/Replenished — .* posted/)).toBeVisible({
      timeout: 15000,
    });
    await expect.poll(() => onShelf(s, "pick"), { timeout: 15000 }).toBe(MAX);
    expect(await onShelf(s, "reserve")).toBe(ON_RESERVE - TO_CARRY);
    expect(await hasAlert(s)).toBe(false);
  });

  test("a transfer held for approval claims the shortage: it is not offered twice and the shelf fills once", async ({
    page,
    authenticatedPage,
  }, testInfo) => {
    void authenticatedPage;
    await writeProfile({ confirm_shelf_by_scan: false });

    // Every transfer of the organisation now waits for a manager's signature.
    const workflow = await api.createWorkflow(token, {
      target_type: "document",
      is_active: true,
      name: `E2E-ReplenRule-Approval-${Date.now().toString(36)}`,
      stages: [
        {
          order: 1,
          role: "manager",
          label: "Manager approval",
          approver_user_ids: [],
        },
      ],
    });
    workflows.push(workflow.id);
    await writeProfile({ approval_required_for_types: ["INT"] });

    const s = await seed(testInfo.workerIndex);
    expect(await hasAlert(s)).toBe(true);
    expect(await taskOf(s)).toBeTruthy();

    // First action: the sheet posts, and the screen says the move is waiting
    // for approval rather than done.
    const sheet = await openTheSheet(page, s);
    const [held] = await Promise.all([
      page.waitForResponse(
        (r) =>
          r.url().includes(`${PROPOSALS}/${s.ruleId}/move`) &&
          r.request().method() === "POST",
      ),
      sheet.getByRole("button", { name: "Post the move" }).click(),
    ]);
    const heldTransfer = (await held.json()) as { id: string; status: string };
    expect(heldTransfer.status).toBe("PENDING_APPROVAL");
    await expect(page.getByText(/is waiting for approval/)).toBeVisible({
      timeout: 15000,
    });
    await expect(sheet).toBeHidden();

    // The hold moved nothing: the goods are reserved at the source, not on
    // the pick face.
    expect(await onShelf(s, "pick")).toBe(ON_PICK_FACE);
    expect(await onShelf(s, "reserve")).toBe(ON_RESERVE);

    // The shortage is claimed. The alert is gone from the reorder screen and
    // the task is gone from Start, so there is no second button to press.
    expect(await hasAlert(s)).toBe(false);
    expect(await taskOf(s)).toBeUndefined();
    await page.goto("/purchase-orders/reorder-rules");
    await expect(
      page.getByRole("heading", { name: "Reorder rules" }).first(),
    ).toBeVisible({ timeout: 15000 });
    await expect(
      page.getByRole("listitem").filter({ hasText: s.productName }),
    ).toHaveCount(0);
    await page.goto("/warehouse/todo");
    await expect(page.getByRole("heading", { name: "What are we doing?" })).toBeVisible();
    await expect(page.getByText(carrySentence(s))).toHaveCount(0);

    // An old link to the task opens nothing to carry.
    await page.goto(`/warehouse/todo?replenish=${s.ruleId}`);
    await expect(
      page.getByRole("dialog", { name: "Replenish from reserve" }),
    ).toHaveCount(0);

    // A second action by any other door is refused, and a purchase is not
    // drafted for a shortage that is already on its way.
    const proposal = await ctx.get(`${PROPOSALS}/${s.ruleId}`, {
      headers: auth(),
    });
    expect((await proposal.json()).lines).toEqual([]);
    const again = await ctx.post(`${PROPOSALS}/${s.ruleId}/move`, {
      headers: auth(),
    });
    expect(again.status()).toBe(400);
    const draft = await ctx.post(DRAFT_POS, {
      headers: auth(),
      data: { reorder_rule_ids: [s.ruleId] },
    });
    expect((await draft.json()).created).toEqual([]);

    // Nothing moved by all of that.
    expect(await onShelf(s, "pick")).toBe(ON_PICK_FACE);
    expect(await onShelf(s, "reserve")).toBe(ON_RESERVE);

    // One approval, one move: the shelf reaches its maximum, not the sum of
    // two proposals.
    await api.approveDocument(token, heldTransfer.id);
    await expect.poll(() => onShelf(s, "pick"), { timeout: 15000 }).toBe(MAX);
    expect(await onShelf(s, "reserve")).toBe(ON_RESERVE - TO_CARRY);
    expect(await hasAlert(s)).toBe(false);
  });
});
