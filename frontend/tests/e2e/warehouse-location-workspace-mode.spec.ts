import { type Page } from "@playwright/test";
import { test, expect } from "./fixtures/auth";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";
import { ApiHelper } from "./helpers/api";
import { decodeLabel, download } from "./helpers/label-decode";
import { pickLocationSettingsPlace } from "./helpers/location-settings";

/**
 * From home to business, with the stickers already on the shelves.
 *
 * A household's shelves carry random codes (`LOC-7KQ2`), printed as bars and
 * as a QR that holds a web address. When the same organization switches to a
 * business way of working nothing is renumbered, and every sticker on every
 * shelf has to go on naming its shelf — in receiving, in picking and in a
 * stock take — both when a USB scanner types the code and when a 2D scanner
 * types the whole address of the QR. The same has to hold after the owner
 * chooses "Renumber by template" and the shelves get codes that read like
 * their place.
 *
 * The three places are asked the way the floor asks them: a keyboard-wedge
 * scanner types the code, a few milliseconds a key, and ends it with Enter,
 * with the focus nowhere in particular. A wrong shelf is scanned first in each
 * place, so that "the code lands on the right location" is a difference the
 * screen shows and not a sentence it always says.
 *
 * The switch rewrites the organization's profile and its module set, so this
 * spec runs alone (the `org-profile` project) and puts both back in `afterAll`.
 */

const HOME = "Food & Home";
const BUSINESS = "Equipment & Warehouse";
const HOME_ID = "food_home";
const WORKSPACE_URL = "/settings/my-modules";
/**
 * A walk of `everywhere()`: three readings, each a delivery, an order and a
 * count set up through the API and opened in the browser — nine page loads,
 * which the default 30 s does not cover on a loaded machine.
 */
const WALK_TIMEOUT = 120_000;

interface Shelf {
  id: string;
  name: string;
  /** What is printed on the sticker today. */
  code: string;
}

/** Everything a sticker can say: the bars' code, and what the QR carries. */
interface Sticker {
  shelf: Shelf;
  bars: string;
  /** What decoding the printed QR gives: the code, or an address holding it. */
  qr: string;
  /**
   * The address a 2D scanner types for the QR. An instance with a public
   * address prints it in the QR; this stack has none, so its QR holds the bare
   * code and the address is the shape the first stickers carried (`/s/<code>`).
   */
  qrAddress: string;
}

async function currentProfileName(page: Page): Promise<string> {
  const badge = page.getByText(/^current$/i).first();
  await expect(badge).toBeVisible({ timeout: 15000 });
  const radio = page
    .locator("li", { has: badge })
    .locator('input[type="radio"]');
  const name = await radio.getAttribute("aria-label");
  if (!name) throw new Error("Current profile radio has no aria-label");
  return name;
}

/** The switch as a person makes it: pick, read what changes, apply, confirm. */
async function switchProfile(page: Page, targetName: string) {
  await page.getByRole("radio", { name: targetName }).click();
  await expect(
    page.getByRole("heading", { name: "What will change" }),
  ).toBeVisible({ timeout: 15000 });
  const apply = page.getByRole("button", { name: "Apply", exact: true });
  await expect(apply).toBeEnabled({ timeout: 15000 });
  await apply.click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible({ timeout: 10000 });
  await dialog.getByRole("button", { name: /switch workspace mode/i }).click();
  const badge = page.getByText(/^current$/i).first();
  await expect(
    page
      .locator("li", { has: badge })
      .locator(`input[aria-label="${targetName}"]`),
  ).toBeVisible({ timeout: 20000 });
}

/**
 * A scanner typing: every key of the code, then Enter, with the focus nowhere
 * in particular. The keys are raised in the page in one go, the way a scanner
 * sends them (the app takes a burst whose keys come under 50 ms apart as a
 * scan): sent one by one from outside, a busy machine stretches a gap past
 * that and the code arrives cut in two, which is the app doing what it should.
 */
async function scan(page: Page, reading: string) {
  await page.evaluate((code) => {
    (document.activeElement as HTMLElement | null)?.blur();
    const send = (key: string) => {
      document.body.dispatchEvent(
        new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }),
      );
    };
    for (const key of code) send(key);
    send("Enter");
  }, reading);
}

test.describe.serial("Warehouse — from home to business", () => {
  let api: ApiHelper;
  let token: string;
  let uid: string;
  let supplierId: string;
  let customerId: string;
  let warehouse: { id: string; name: string };
  let near: Shelf;
  let far: Shelf;
  let nearSticker: Sticker;
  let farSticker: Sticker;

  // What to put back when the spec is done.
  let originalProfile: string;
  let modulesBefore: string[];
  let confirmByScanBefore: boolean;

  test.beforeAll(async ({ playwright, baseURL }, testInfo) => {
    const ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
    uid = `${Date.now().toString(36)}-w${testInfo.workerIndex}`;

    const org = await ctx.get("/api/v1/organizations/my", {
      headers: { Authorization: `Bearer ${token}` },
    });
    originalProfile = (await org.json()).active_profile_id;
    modulesBefore = await api.getMyModules(token);

    // The household is where this starts, whatever the stack was left as.
    if (originalProfile !== HOME_ID) {
      await ctx.post("/api/v1/onboarding/switch-profile", {
        headers: { Authorization: `Bearer ${token}` },
        data: { profile_id: HOME_ID, dry_run: false },
      });
    }
    await api.enableAllModules(token);

    // Shelves are confirmed by scan, so a wrong label is a wrong label.
    const profile = await ctx.get("/api/v1/warehouse/profile", {
      headers: { Authorization: `Bearer ${token}` },
    });
    confirmByScanBefore = (await profile.json()).confirm_shelf_by_scan;
    await ctx.put("/api/v1/warehouse/profile", {
      headers: { Authorization: `Bearer ${token}` },
      data: { confirm_shelf_by_scan: true },
    });

    const supplier = await api.createPartner(token, {
      name: `E2E-Home-Supplier-${uid}`,
      type: "SUPPLIER",
    });
    supplierId = supplier.id;
    const customer = await api.createPartner(token, {
      name: `E2E-Home-Customer-${uid}`,
      type: "CUSTOMER",
    });
    customerId = customer.id;

    warehouse = {
      id: (
        await api.createStorageIdempotent(token, {
          name: `E2E-Home-WH-${uid}`,
        })
      ).id,
      name: `E2E-Home-WH-${uid}`,
    };
    const shelf = async (label: string): Promise<Shelf> => {
      const name = `E2E-Home-${label}-${uid}`;
      const made = await api.createStorageIdempotent(token, {
        name,
        parent_id: warehouse.id,
      });
      return { id: made.id, name, code: await codeOf(made.id) };
    };
    near = await shelf("Near");
    far = await shelf("Far");

    async function codeOf(id: string): Promise<string> {
      const read = await ctx.get(`/api/v1/locations/${id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      return (await read.json()).short_code;
    }
  });

  test.afterAll(async ({ playwright, baseURL }) => {
    const ctx = await playwright.request.newContext({ baseURL });
    const restore = new ApiHelper(ctx);
    const fresh = (await restore.login(ADMIN_EMAIL, ADMIN_PASSWORD))
      .access_token;
    const org = await ctx.get("/api/v1/organizations/my", {
      headers: { Authorization: `Bearer ${fresh}` },
    });
    if ((await org.json()).active_profile_id !== originalProfile) {
      await ctx.post("/api/v1/onboarding/switch-profile", {
        headers: { Authorization: `Bearer ${fresh}` },
        data: { profile_id: originalProfile, dry_run: false },
      });
    }
    // A profile resets the module set to its preset: give back the modules
    // the suite had switched on.
    const now = await restore.getMyModules(fresh);
    for (const name of modulesBefore.filter((m) => !now.includes(m))) {
      await restore.toggleModule(fresh, name, true).catch(() => {});
    }
    await ctx.put("/api/v1/warehouse/profile", {
      headers: { Authorization: `Bearer ${fresh}` },
      data: { confirm_shelf_by_scan: confirmByScanBefore },
    });
  });

  /** The sticker as it was printed: the bars' code and the QR's address. */
  async function printedSticker(page: Page, shelf: Shelf): Promise<Sticker> {
    const response = await page.request.post(
      "/api/v1/printing/location-labels/png",
      {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          location_ids: [shelf.id],
          qr: true,
          width_mm: 62,
          height_mm: 29,
          copies: 1,
        },
      },
    );
    expect(response.ok(), await response.text()).toBe(true);
    const png = Buffer.from(await response.body());
    const bars = await decodeLabel(page, png, "bars", [0.42, 1]);
    const qr = await decodeLabel(page, png, "qr", [0, 0.42]);
    expect(bars).toBe(shelf.code);
    expect(qr).toContain(shelf.code);
    const qrAddress = /^https?:\/\//.test(qr!)
      ? qr!
      : `${new URL(page.url()).origin}/s/${shelf.code}`;
    return { shelf, bars: bars!, qr: qr!, qrAddress };
  }

  /** A delivery waiting for `shelf`: the receiving screen asks for its label. */
  async function receivingFor(page: Page, shelf: Shelf, tag: string) {
    const template = await api.createProductTemplate(token, {
      name: `E2E-Home-In-${tag}-${uid}`,
    });
    const doc = await api.createDocument(token, {
      type: "IN",
      partner_id: supplierId,
      target_location_id: shelf.id,
      lines: [{ product_template_id: template.id, expected_quantity: 3 }],
    });
    await api.confirmDocument(token, doc.id);
    await page.goto(`/warehouse/documents/${doc.id}`);
    // Under load the document page can still be blank after the default 5 s.
    const scanReceiving = page.getByRole("button", { name: "Scan receiving" });
    await expect(scanReceiving).toBeVisible({ timeout: 30000 });
    await scanReceiving.click();
    const sheet = page.getByRole("dialog", { name: "Receive stock" });
    await expect(sheet.getByText("Scan the location to confirm")).toBeVisible({
      timeout: 15000,
    });
    return sheet;
  }

  /** An order waiting to be picked from `shelf`. */
  async function pickingFrom(page: Page, shelf: Shelf, tag: string) {
    const item = await api.createItem(token, {
      name: `E2E-Home-Out-${tag}-${uid}`,
      quantity: 5,
      location_id: shelf.id,
    });
    const doc = await api.createDocument(token, {
      type: "OUT",
      partner_id: customerId,
      source_location_id: shelf.id,
      lines: [{ item_id: item.id, expected_quantity: 2 }],
    });
    await api.confirmDocument(token, doc.id);
    await page.goto(`/warehouse/documents/${doc.id}`);
    const scanPicking = page.getByRole("button", { name: "Scan picking" });
    await expect(scanPicking).toBeVisible({ timeout: 30000 });
    await scanPicking.click();
    const sheet = page.getByRole("dialog", { name: "Picking" });
    await expect(sheet.getByText("Scan the location label")).toBeVisible({
      timeout: 15000,
    });
    return sheet;
  }

  /**
   * Every sticker reading of one shelf, in all three places: the shelf's own
   * label confirms it, and the other shelf's label does not.
   */
  async function everywhere(
    page: Page,
    sticker: Sticker,
    other: Sticker,
    readings: Record<string, string>,
    wrong: Record<string, string>,
  ) {
    // One count may be open on a location at a time: this one serves every
    // reading, and is deleted before the next call opens its own.
    const take = await api.createStockTake(token, {
      name: `E2E-Home-Count-${uid}-${Date.now().toString(36)}`,
      location_id: warehouse.id,
    });
    for (const [how, reading] of Object.entries(readings)) {
      const tag = `${how}-${Date.now().toString(36)}`;

      const receiving = await receivingFor(page, sticker.shelf, tag);
      await scan(page, wrong[how]);
      await expect(
        page.getByText(/That is not the location — go to/),
      ).toBeVisible();
      await expect(receiving.getByText("Location confirmed")).toHaveCount(0);
      await scan(page, reading);
      await expect(receiving.getByText("Location confirmed")).toBeVisible();

      const picking = await pickingFrom(page, sticker.shelf, tag);
      await scan(page, wrong[how]);
      await expect(
        page.getByText(/That is not the location — go to/),
      ).toBeVisible();
      await expect(picking.getByText("Location confirmed")).toHaveCount(0);
      await scan(page, reading);
      await expect(picking.getByText("Location confirmed")).toBeVisible();

      await page.goto(`/inventory/stock-takes/${take.id}/counting`);
      const field = page.getByTestId("stock-take-counting-input");
      // The bar is drawn from the scan's answer, and that answer is a lookup
      // like the ones above: under load it can take longer than the default
      // 5 s. Wait for it by name, so a refused or failed lookup says so
      // instead of showing up as a bar that never appeared.
      const answered = page.waitForResponse(
        (response) =>
          response.request().method() === "GET" &&
          response.url().includes("/api/v1/labels/scan/"),
        { timeout: 30000 },
      );
      await field.fill(reading);
      await field.press("Enter");
      const answer = await answered;
      expect(answer.status(), `scan of ${how}: ${await answer.text()}`).toBe(
        200,
      );
      const counting = page.getByText("Counting location:");
      await expect(counting).toContainText(sticker.shelf.name, {
        timeout: 15000,
      });
      await expect(counting).not.toContainText(other.shelf.name);
    }
    await api.deleteStockTake(token, take.id);
  }

  test("at home the shelves carry random codes, printed as bars and as a QR address", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/warehouse/todo");
    // The decoder runs in this page: a page still settling navigates under it.
    await expect(
      page.getByRole("heading", { name: "What are we doing?" }),
    ).toBeVisible({ timeout: 15000 });
    nearSticker = await printedSticker(page, near);
    farSticker = await printedSticker(page, far);
    for (const sticker of [nearSticker, farSticker]) {
      expect(sticker.bars).toMatch(/^LOC-/);
      expect(sticker.qrAddress).toMatch(/^https?:\/\/.+\/s\/LOC-/);
    }

    await page.goto(WORKSPACE_URL);
    expect(await currentProfileName(page)).toBe(HOME);
  });

  test("after the switch no sticker changes and every one still names its shelf", async ({
    page,
    authenticatedPage,
  }) => {
    test.setTimeout(WALK_TIMEOUT);
    await page.goto(WORKSPACE_URL);
    await switchProfile(page, BUSINESS);
    // A profile starts from its own module set; the floor needs these on.
    await api.enableAllModules(token);

    // Nothing was renumbered by the switch.
    for (const sticker of [nearSticker, farSticker]) {
      const read = await page.request.get(
        `/api/v1/locations/${sticker.shelf.id}`,
        { headers: { Authorization: `Bearer ${token}` } },
      );
      expect((await read.json()).short_code).toBe(sticker.bars);
    }

    // The warehouse now numbers by its template, and says nothing is waiting
    // to be replaced: renumbering is on offer, not done.
    await page.goto("/warehouse/location-settings");
    await pickLocationSettingsPlace(page, warehouse.name);
    await expect(
      page.getByRole("button", { name: "Renumber by template" }),
    ).toBeVisible({ timeout: 15000 });
    await expect(page.getByText(/stickers? to replace/)).toHaveCount(0);

    await everywhere(
      page,
      nearSticker,
      farSticker,
      {
        "old bars": nearSticker.bars,
        "old QR": nearSticker.qr,
        "old QR address": nearSticker.qrAddress,
      },
      {
        "old bars": farSticker.bars,
        "old QR": farSticker.qr,
        "old QR address": farSticker.qrAddress,
      },
    );
  });

  test("after renumbering by template the old stickers still scan beside the new codes", async ({
    page,
    authenticatedPage,
  }) => {
    test.setTimeout(WALK_TIMEOUT);
    await page.goto("/warehouse/location-settings");
    await pickLocationSettingsPlace(page, warehouse.name);
    await page.getByRole("button", { name: "Renumber by template" }).click();
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: "Renumber by template" })
      .click();
    await expect(page.getByText("2 codes changed")).toBeVisible({
      timeout: 15000,
    });

    // Both shelves read like their place now, and both old stickers are
    // listed for replacing, old code first.
    const codes = new Map<string, string>();
    for (const { id } of [near, far]) {
      const read = await page.request.get(`/api/v1/locations/${id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      codes.set(id, (await read.json()).short_code);
    }
    for (const sticker of [nearSticker, farSticker]) {
      const now = codes.get(sticker.shelf.id)!;
      expect(now).not.toMatch(/^LOC-/);
      await expect(
        page
          .getByRole("region", { name: "2 stickers to replace" })
          .getByRole("listitem")
          .filter({ hasText: sticker.shelf.name }),
      ).toContainText(`${sticker.bars} → ${now}`);
    }

    // The new code, the old bars and the old QR address all land on the
    // shelf they name.
    await everywhere(
      page,
      nearSticker,
      farSticker,
      {
        "new code": codes.get(near.id)!,
        "old bars": nearSticker.bars,
        "old QR address": nearSticker.qrAddress,
      },
      {
        "new code": codes.get(far.id)!,
        "old bars": farSticker.bars,
        "old QR address": farSticker.qrAddress,
      },
    );
  });

  test("with Warehouse as the only module shown, the shelf labels preview, download and queue", async ({
    page,
    authenticatedPage,
  }) => {
    // The printer is announced the way an agent does it; one name, one printer.
    const register = await page.request.post(
      "/api/v1/printing/agent/register",
      {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          name: "E2E-Label-Printer",
          printer_type: "zebra",
          agent_version: "1.0.0",
          protocol_version: 1,
        },
      },
    );
    expect(register.ok(), await register.text()).toBe(true);

    const focus = await page.request.post("/api/v1/modules/focus", {
      headers: { Authorization: `Bearer ${token}` },
      data: { module_name: "warehouse" },
    });
    expect(focus.ok(), await focus.text()).toBe(true);
    try {
      await page.goto("/warehouse/location-settings");
      await expect(
        page.getByRole("heading", { name: "Codes and labels", level: 1 }),
      ).toBeVisible({ timeout: 15000 });
      await pickLocationSettingsPlace(page, warehouse.name);
      await page.getByRole("checkbox", { name: `Select ${near.name}` }).check();
      await page
        .getByRole("button", { name: "Print labels", exact: true })
        .click();
      const sheet = page.getByRole("dialog", { name: "Location labels" });
      await expect(
        sheet.getByRole("img", { name: "Preview of the location labels" }),
      ).toBeVisible({ timeout: 15000 });
      await sheet
        .getByRole("checkbox", {
          name: "QR beside the bars, for a phone camera",
        })
        .check();

      // The file is the label of that shelf, bars and QR, in the module.
      const file = await download(page, () =>
        sheet.getByRole("button", { name: "Download 1 label" }).click(),
      );
      const code = await page.request
        .get(`/api/v1/locations/${near.id}`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        .then(async (r) => (await r.json()).short_code);
      expect(await decodeLabel(page, file.bytes, "bars", [0.42, 1])).toBe(code);
      expect(await decodeLabel(page, file.bytes, "qr", [0, 0.42])).toContain(
        code,
      );

      // And the same label goes to the printer's queue from the same sheet.
      const queued = page.waitForRequest(
        (request) =>
          request.method() === "POST" &&
          request.url().endsWith("/printing/jobs"),
      );
      await sheet.getByRole("button", { name: "Send to printer" }).click();
      const body = (await queued).postDataJSON();
      expect(body.location_ids).toEqual([near.id]);
      expect(body.qr).toBe(true);
      await expect(page.getByText("Sent to E2E-Label-Printer")).toBeVisible();
    } finally {
      await page.request.delete("/api/v1/modules/focus", {
        headers: { Authorization: `Bearer ${token}` },
      });
    }
  });
});
