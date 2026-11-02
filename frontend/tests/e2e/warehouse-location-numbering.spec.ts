import { type APIRequestContext, type Page } from "@playwright/test";
import { test, expect } from "./fixtures/auth";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";
import { ApiHelper } from "./helpers/api";
import { decodeLabel, download } from "./helpers/label-decode";
import { pickLocationSettingsPlace } from "./helpers/location-settings";

/**
 * A business numbers its shelves like the shelf reads — zone A, rack 2, level
 * 1 is `A-02-01` — and a sticker already on a shelf is never made wrong by it.
 *
 * What is asserted here is what the person sees and scans: the code a new
 * location is given on the Locations screen, what moving a location does to
 * its code (nothing — the sticker is on the shelf), what "Renumber by
 * template" lists for replacing, and that the old sticker still names its
 * shelf afterwards. A renumbering started from a zone leaves the sibling
 * zones' stickers alone. The label sheet is covered in the last block.
 *
 * Every warehouse carries its own template, set through the API on the
 * warehouse this spec creates, so the organization's profile is not touched
 * (the home-to-business switch has its own spec).
 */

const TREE_TEMPLATE = "{zone}-{rack:02}-{level:02}";

// One worker, one test at a time, for the whole file: the tests of a block
// share the places the block set up in `beforeAll`, and they are walked in
// the order they were written.
test.describe.configure({ mode: "serial" });

interface Place {
  id: string;
  name: string;
}

interface Session {
  api: ApiHelper;
  ctx: APIRequestContext;
  token: string;
  uid: string;
}

async function startSession(
  playwright: {
    request: { newContext: (o: object) => Promise<APIRequestContext> };
  },
  baseURL: string | undefined,
  workerIndex: number,
): Promise<Session> {
  const ctx = await playwright.request.newContext({ baseURL });
  const api = new ApiHelper(ctx);
  const token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
  await api.enableAllModules(token);
  return {
    api,
    ctx,
    token,
    uid: `${Date.now().toString(36)}-w${workerIndex}`,
  };
}

async function place(s: Session, name: string, parent?: Place): Promise<Place> {
  const made = await s.api.createStorageIdempotent(s.token, {
    name,
    ...(parent ? { parent_id: parent.id } : {}),
  });
  return { id: made.id, name };
}

/** The code on a location's sticker, read from the register. */
async function codeOf(s: Session, id: string): Promise<string> {
  const response = await s.ctx.get(`/api/v1/locations/${id}`, {
    headers: { Authorization: `Bearer ${s.token}` },
  });
  return (await response.json()).short_code;
}

async function setTemplate(s: Session, warehouse: Place, template: string) {
  const response = await s.ctx.put(
    `/api/v1/locations/${warehouse.id}/code-template`,
    {
      headers: { Authorization: `Bearer ${s.token}` },
      data: { template },
    },
  );
  expect(response.ok(), await response.text()).toBe(true);
}

/** What scanning a code resolves to: the location it names. */
async function scanned(s: Session, code: string): Promise<string | null> {
  const response = await s.ctx.get(`/api/v1/labels/scan/${code}`, {
    headers: { Authorization: `Bearer ${s.token}` },
  });
  if (!response.ok()) return null;
  return (await response.json()).location?.name ?? null;
}

/** Opens Inventory → Locations on one location. The tree opens the branches
 *  above it and its own, so the codes of what stands inside are on screen. */
async function openLocation(page: Page, location: Place) {
  await page.goto(`/inventory/locations/${location.id}`);
  await expect(
    page.getByRole("heading", { name: location.name, level: 2 }),
  ).toBeVisible();
}

/** The code the tree shows next to a location's name. */
function treeCode(page: Page, name: string) {
  return page.getByRole("treeitem", { name: new RegExp(`${name} `) }).first();
}

/** Warehouse → Codes and labels, on one warehouse (or zone) of the list. */
async function openCodes(page: Page, path: string) {
  await page.goto("/warehouse/location-settings");
  await expect(
    page.getByRole("heading", { name: "Codes and labels", level: 1 }),
  ).toBeVisible();
  await pickLocationSettingsPlace(page, path);
  await expect(
    page.getByRole("heading", { name: "Location codes" }),
  ).toBeVisible();
}

async function addInside(page: Page, parent: string, name: string) {
  await page.getByRole("button", { name: "Add location inside" }).click();
  const wizard = page.getByRole("dialog", { name: "Location Wizard" });
  // The wizard asks what is inside the location that was open. Typed on any
  // other step, the name would make a top-level location of its own.
  await expect(
    wizard.getByRole("heading", {
      name: `What is inside this location? — ${parent}`,
    }),
  ).toBeVisible();
  await wizard.getByRole("textbox").fill(name);
  await wizard.getByRole("button", { name: "Done" }).click();
  await expect(wizard).toBeHidden();
}

test.describe("Warehouse — business location numbering", () => {
  let s: Session;
  let warehouse: Place;
  let zoneA: Place;
  let rackA1: Place;

  test.beforeAll(async ({ playwright, baseURL }, testInfo) => {
    s = await startSession(playwright, baseURL, testInfo.workerIndex);
    warehouse = await place(s, `E2E-Num-WH-${s.uid}`);
    await setTemplate(s, warehouse, TREE_TEMPLATE);
    zoneA = await place(s, `E2E-Num-ZoneA-${s.uid}`, warehouse);
    rackA1 = await place(s, `E2E-Num-Rack1-${s.uid}`, zoneA);
  });

  test("a new location takes the next code among its neighbours", async ({
    page,
    authenticatedPage,
  }) => {
    // Codes are one namespace for the organization, because a scan has to
    // name one shelf: the first zone of this warehouse is whichever letter is
    // free, and everything under it reads off that letter.
    const zone = await codeOf(s, zoneA.id);
    expect(zone).toMatch(/^[A-Z]+$/);
    const rack1Code = await codeOf(s, rackA1.id);
    expect(rack1Code).toMatch(new RegExp(`^${zone}-\\d\\d$`));

    await openLocation(page, zoneA);
    const rack2 = `E2E-Num-Rack2-${s.uid}`;
    await addInside(page, zoneA.name, rack2);

    // The tree shows the code the screen gave it, before anyone scans it: the
    // zone's letter and a number after the neighbour's. (A number an old
    // sticker of the organization carried is skipped, so the exact number
    // depends on the database; that it follows the neighbour does not.)
    const rack2Id = (await s.api.listStorages(s.token)).find(
      (x) => x.name === rack2,
    )!.id;
    const rack2Code = await codeOf(s, rack2Id);
    expect(rack2Code).toMatch(new RegExp(`^${zone}-\\d\\d$`));
    expect(Number(rack2Code.slice(-2))).toBeGreaterThan(
      Number(rack1Code.slice(-2)),
    );
    await expect(treeCode(page, rack2)).toContainText(rack2Code);

    // A level under that rack continues from its code.
    await treeCode(page, rack2).click();
    await expect(
      page.getByRole("heading", { name: rack2, level: 2 }),
    ).toBeVisible();
    const level = `E2E-Num-Level1-${s.uid}`;
    await addInside(page, rack2, level);
    const levelId = (await s.api.listStorages(s.token)).find(
      (x) => x.name === level,
    )!.id;
    const levelCode = await codeOf(s, levelId);
    expect(levelCode).toMatch(new RegExp(`^${rack2Code}-\\d\\d$`));
    await expect(treeCode(page, level)).toContainText(levelCode);

    // A second zone under the warehouse is a letter code of its own.
    await openLocation(page, warehouse);
    const zoneB = `E2E-Num-ZoneB-${s.uid}`;
    await addInside(page, warehouse.name, zoneB);
    const second = (await s.api.listStorages(s.token)).find(
      (x) => x.name === zoneB,
    );
    const secondCode = await codeOf(s, second!.id);
    expect(secondCode).toMatch(/^[A-Z]+$/);
    expect(secondCode).not.toBe(zone);
    await expect(treeCode(page, zoneB)).toContainText(secondCode);
  });

  test("a location added right behind choosing a zone goes into that zone", async ({
    page,
    authenticatedPage,
    browserName,
  }) => {
    test.skip(browserName !== "chromium", "CPU throttling is a Chromium tool");
    // Six rounds at an eighth of the speed, beside every top-level location
    // of the database: a search would replace the tree with a list, so the
    // tree is not narrowed to this warehouse. The rounds took 50 s on a
    // shared host at load 26 and over 90 s at load 35-40, the same before
    // and after the tree started loading a level at a time.
    test.setTimeout(180_000);
    const wh = await place(s, `E2E-Num-Quick-WH-${s.uid}`);
    await setTemplate(s, wh, TREE_TEMPLATE);
    const zones = [
      await place(s, `E2E-Num-QuickA-${s.uid}`, wh),
      await place(s, `E2E-Num-QuickB-${s.uid}`, wh),
      await place(s, `E2E-Num-QuickC-${s.uid}`, wh),
    ];
    await openLocation(page, wh);
    // A slow machine, so the pane of the zone that was open is still on the
    // screen when the next press arrives.
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: 8 });

    for (const [index, zone] of [...zones, ...zones].entries()) {
      await page
        .getByRole("treeitem", {
          name: new RegExp(`^(Collapse |Expand )?${zone.name} `),
        })
        .first()
        .click();
      await page.getByRole("button", { name: "Add location inside" }).click();
      const wizard = page.getByRole("dialog", { name: "Location Wizard" });
      const name = `E2E-Num-QuickChild${index}-${s.uid}`;
      await wizard.getByRole("textbox").fill(name);
      await wizard.getByRole("button", { name: "Done" }).click();
      // The save, at an eighth of the speed, took up to 6.6 s.
      await expect(wizard).toBeHidden({ timeout: 15_000 });

      const made = (await s.api.listStorages(s.token)).find(
        (x) => x.name === name,
      ) as { parent_id?: string | null } | undefined;
      expect(made?.parent_id, `${name} sits in ${zone.name}`).toBe(zone.id);
    }
  });

  test("moving a location leaves its sticker alone; renumbering lists it to replace", async ({
    page,
    authenticatedPage,
  }) => {
    const wh = await place(s, `E2E-Num-Move-WH-${s.uid}`);
    await setTemplate(s, wh, TREE_TEMPLATE);
    const from = await place(s, `E2E-Num-From-${s.uid}`, wh);
    const to = await place(s, `E2E-Num-To-${s.uid}`, wh);
    const stays = await place(s, `E2E-Num-Stays-${s.uid}`, from);
    const moves = await place(s, `E2E-Num-Moves-${s.uid}`, from);
    const fromCode = await codeOf(s, from.id);
    const toCode = await codeOf(s, to.id);
    const oldCode = await codeOf(s, moves.id);
    expect(oldCode).toMatch(new RegExp(`^${fromCode}-\\d\\d$`));

    // Reorganize: the rack is carried to the other zone.
    await openLocation(page, moves);
    await page.getByRole("button", { name: "Move to…" }).click();
    const dialog = page.getByRole("dialog", { name: "Move to…" });
    await dialog.getByPlaceholder("Search the destination").fill(to.name);
    await dialog
      .getByRole("list", { name: "Destination locations" })
      .getByRole("button", { name: new RegExp(`^${to.name} `) })
      .click();
    await expect(page.getByText("Location moved")).toBeVisible();

    // The sticker is on the shelf: the move does not touch the code. It no
    // longer reads like its place, and nothing yet asks anyone to replace it.
    expect(await codeOf(s, moves.id)).toBe(oldCode);
    await expect(treeCode(page, moves.name)).toContainText(oldCode);

    await openCodes(page, wh.name);
    await expect(page.getByText(/stickers? to replace/)).toHaveCount(0);

    await page.getByRole("button", { name: "Renumber by template" }).click();
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: "Renumber by template" })
      .click();
    await expect(page.getByText("1 code changed")).toBeVisible();

    // The rack now reads like its new zone, the one that stayed is untouched,
    // and the card lists exactly the sticker to replace, old code first.
    // (A number an old sticker of the organization carried is never reused,
    // so which number it is depends on the database; that it reads off the
    // new zone does not.)
    const newCode = await codeOf(s, moves.id);
    expect(newCode).toMatch(new RegExp(`^${toCode}-\\d\\d$`));
    expect(await codeOf(s, stays.id)).toBe(`${fromCode}-01`);
    const list = page.getByRole("region", { name: "1 sticker to replace" });
    await expect(list).toBeVisible();
    await expect(list.getByRole("listitem")).toHaveCount(1);
    await expect(list.getByRole("listitem")).toContainText(moves.name);
    await expect(list.getByRole("listitem")).toContainText(
      `${oldCode} → ${newCode}`,
    );

    // Old stickers keep scanning, to the same shelf, whichever code is read.
    expect(await scanned(s, oldCode)).toBe(moves.name);
    expect(await scanned(s, newCode)).toBe(moves.name);

    // Stick the new label on: the list empties, and the old code still names
    // the shelf for as long as the old sticker lies around.
    await list.getByRole("button", { name: "Mark as replaced" }).click();
    await expect(page.getByText(/stickers? to replace/)).toHaveCount(0);
    expect(await scanned(s, oldCode)).toBe(moves.name);
  });

  test("renumbering from one zone leaves the other zones' stickers alone", async ({
    page,
    authenticatedPage,
  }) => {
    // A warehouse that was numbered at random, with two zones of two racks.
    const wh = await place(s, `E2E-Num-Zone-WH-${s.uid}`);
    await setTemplate(s, wh, "LOC");
    const zones: Array<{ zone: Place; racks: Place[] }> = [];
    for (const letter of ["One", "Two"]) {
      const zone = await place(s, `E2E-Num-Zone${letter}-${s.uid}`, wh);
      const racks = [
        await place(s, `E2E-Num-Zone${letter}-RackA-${s.uid}`, zone),
        await place(s, `E2E-Num-Zone${letter}-RackB-${s.uid}`, zone),
      ];
      zones.push({ zone, racks });
    }
    const [one, two] = zones;
    const before = new Map<string, string>();
    for (const { zone, racks } of zones) {
      for (const p of [zone, ...racks]) before.set(p.id, await codeOf(s, p.id));
    }
    for (const code of before.values()) expect(code).toMatch(/^LOC-/);

    // The template is changed on the card, and changing it rewrites nothing.
    await openCodes(page, wh.name);
    await page.getByRole("button", { name: "Code template" }).click();
    const sheet = page.getByRole("dialog", { name: "Code template" });
    await sheet.getByLabel("Template").fill(TREE_TEMPLATE);
    await sheet.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Code template saved")).toBeVisible();
    await expect(
      page.getByText(`Codes from the template ${TREE_TEMPLATE}`, {
        exact: false,
      }),
    ).toBeVisible();
    for (const [id, code] of before) expect(await codeOf(s, id)).toBe(code);

    // Renumber from the first zone: its branch is numbered, the other is not.
    await openCodes(page, `${wh.name} → ${one.zone.name}`);
    await page.getByRole("button", { name: "Renumber by template" }).click();
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: "Renumber by template" })
      .click();
    await expect(page.getByText("3 codes changed")).toBeVisible();

    const zoneCode = await codeOf(s, one.zone.id);
    expect(zoneCode).toMatch(/^[A-Z]+$/);
    // Racks read off the zone's letter and follow the walk order (A before
    // B); the numbers an old sticker of the organization carried are skipped.
    const rackCodes = [
      await codeOf(s, one.racks[0].id),
      await codeOf(s, one.racks[1].id),
    ];
    const pattern = new RegExp(`^${zoneCode}-(\\d\\d)$`);
    const numbers = rackCodes.map((code) => Number(pattern.exec(code)?.[1]));
    expect(numbers.every((n) => n > 0)).toBe(true);
    expect(numbers[0]).toBeLessThan(numbers[1]);
    for (const p of [two.zone, ...two.racks]) {
      expect(await codeOf(s, p.id), p.name).toBe(before.get(p.id));
    }

    // Three stickers to replace, all of them in the zone that was renumbered.
    const list = page.getByRole("region", { name: "3 stickers to replace" });
    await expect(list.getByRole("listitem")).toHaveCount(3);
    await expect(list).toContainText(one.zone.name);
    await expect(list).not.toContainText(two.zone.name);
    // Every old sticker, the zone's too, still names its place.
    expect(await scanned(s, before.get(one.zone.id)!)).toBe(one.zone.name);
    expect(await scanned(s, before.get(one.racks[1].id)!)).toBe(
      one.racks[1].name,
    );
  });
});

test.describe("Warehouse — location labels", () => {
  let s: Session;
  let warehouse: Place;
  let rack: Place;
  let rackCode: string;
  let printerName: string;

  test.beforeAll(async ({ playwright, baseURL }, testInfo) => {
    s = await startSession(playwright, baseURL, testInfo.workerIndex);
    warehouse = await place(s, `E2E-Lbl-WH-${s.uid}`);
    await setTemplate(s, warehouse, TREE_TEMPLATE);
    const zone = await place(s, `E2E-Lbl-Zone-${s.uid}`, warehouse);
    rack = await place(s, `E2E-Lbl-Rack-${s.uid}`, zone);
    rackCode = await codeOf(s, rack.id);
    // One printer, the way an agent announces itself; the same name again is
    // the same printer, so runs do not pile printers up.
    printerName = "E2E-Label-Printer";
    const response = await s.ctx.post("/api/v1/printing/agent/register", {
      headers: { Authorization: `Bearer ${s.token}` },
      data: {
        name: printerName,
        printer_type: "zebra",
        agent_version: "1.0.0",
        protocol_version: 1,
      },
    });
    expect(response.ok(), await response.text()).toBe(true);
  });

  /** The Codes and labels list, the rack ticked, its label sheet open. */
  async function openRackLabel(page: Page) {
    await openCodes(page, warehouse.name);
    await page.getByRole("checkbox", { name: `Select ${rack.name}` }).check();
    await page
      .getByRole("button", { name: "Print labels", exact: true })
      .click();
    const sheet = page.getByRole("dialog", { name: "Location labels" });
    await expect(sheet).toBeVisible();
    return sheet;
  }

  test("the sheet previews the label, and the download is the label it shows", async ({
    page,
    authenticatedPage,
  }) => {
    const sheet = await openRackLabel(page);

    // The preview is the rendered file, not a placeholder.
    const preview = sheet.getByRole("img", {
      name: "Preview of the location labels",
    });
    await expect(preview).toBeVisible();
    await expect
      .poll(() => preview.evaluate((img: HTMLImageElement) => img.naturalWidth))
      .toBeGreaterThan(0);

    // Without the QR: the file carries the bars and nothing for a phone.
    const bars = await download(page, () =>
      sheet.getByRole("button", { name: "Download 1 label" }).click(),
    );
    expect(bars.name).toBe("shelf-labels.png");
    expect(bars.bytes.subarray(1, 4).toString()).toBe("PNG");
    expect(await decodeLabel(page, bars.bytes, "bars")).toBe(rackCode);
    expect(await decodeLabel(page, bars.bytes, "qr")).toBeNull();

    // With the QR beside them: a second request is made for it, the preview
    // is drawn again, and the file now holds both readings of the same shelf.
    const requested = page.waitForRequest(
      (request) =>
        request.url().endsWith("/printing/location-labels/png") &&
        request.postDataJSON().qr === true,
    );
    await sheet
      .getByRole("checkbox", { name: "QR beside the bars, for a phone camera" })
      .check();
    await requested;
    const both = await download(page, () =>
      sheet.getByRole("button", { name: "Download 1 label" }).click(),
    );
    // The QR is drawn on the left of the sheet and the bars on the right.
    expect(await decodeLabel(page, both.bytes, "bars", [0.42, 1])).toBe(
      rackCode,
    );
    const qr = await decodeLabel(page, both.bytes, "qr", [0, 0.42]);
    expect(qr).not.toBeNull();
    // The QR carries the code, alone or inside the address the app opens.
    expect(qr).toContain(rackCode);
  });

  test("a label sent to the printer is queued with its code, size and QR", async ({
    page,
    authenticatedPage,
  }) => {
    const sheet = await openRackLabel(page);
    await sheet
      .getByRole("checkbox", { name: "QR beside the bars, for a phone camera" })
      .check();

    const queued = page.waitForRequest(
      (request) =>
        request.method() === "POST" && request.url().endsWith("/printing/jobs"),
    );
    await sheet.getByRole("button", { name: "Send to printer" }).click();
    const body = (await queued).postDataJSON();
    expect(body.location_ids).toEqual([rack.id]);
    expect(body.bars).toBe(true);
    expect(body.qr).toBe(true);

    await expect(page.getByText(`Sent to ${printerName}`)).toBeVisible();
    // Sending closes the sheet, the way a finished print does.
    await expect(sheet).toBeHidden();

    // The queue holds the job for the printer's agent: this shelf's code.
    const jobs = await s.ctx.get("/api/v1/printing/jobs", {
      headers: { Authorization: `Bearer ${s.token}` },
    });
    const job = (await jobs.json()).items.find((j: { short_codes: string[] }) =>
      j.short_codes.includes(rackCode),
    );
    expect(job).toBeDefined();
    expect(job.status).toBe("queued");
    expect(job.count).toBe(1);
    expect(job.short_codes).toEqual([rackCode]);
  });
});
