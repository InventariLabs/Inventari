import { test, expect } from "./fixtures/camera";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

// A real GTIN-style code the stack has no record of, and a label code the
// stack does know.
const UNKNOWN_EAN = "5901234123457";

// A phone held upright: the priority form factor, and the one whose viewfinder
// the reader's crop is computed for.
test.use({ viewport: { width: 390, height: 844 } });

test.describe("Scan — fake camera", () => {
  let labelShortCode: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const api = new ApiHelper(await playwright.request.newContext({ baseURL }));
    const { access_token } = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    labelShortCode = (await api.generateLabels(access_token, 1, "CAM"))[0]
      .short_code;
  });

  // `camera` installs the fake before the first navigation.
  test.beforeEach(async ({ page, camera: _camera }) => {
    await page.goto("/inventory/scan");
  });

  async function openCamera(page: import("@playwright/test").Page) {
    // A phone starts the camera by itself; a desktop waits for the button.
    // The page is the first this test loads, so it gets the 15 s every other
    // first load in this file gets, not the 5 s default meant for a page
    // already standing.
    const video = page.locator("#qr-reader video");
    const start = page.getByRole("button", { name: "Start Camera" });
    await expect(video.or(start)).toBeVisible({ timeout: 15000 });
    if (await start.isVisible()) await start.click();
    await expect(video).toBeVisible({ timeout: 10000 });
  }

  test("reads an EAN-13 held in front of the camera", async ({
    page,
    camera,
  }) => {
    await openCamera(page);
    await camera.showEan13(UNKNOWN_EAN);
    await expect
      .poll(() => camera.scanRequests(), { timeout: 10000 })
      .toContain(UNKNOWN_EAN);
  });

  test("reads a QR code held in front of the camera", async ({
    page,
    camera,
  }) => {
    await openCamera(page);
    await camera.showQr(labelShortCode);
    await expect
      .poll(() => camera.scanRequests(), { timeout: 10000 })
      .toContain(labelShortCode);
  });

  test("an upright phone's scan page does not scroll", async ({ page }) => {
    // The shell padded the bottom bar's room into the page and still sized
    // its content to the whole screen below the app bar: every short page on
    // a phone scrolled by the bar's height, the scanner included.
    await openCamera(page);
    const { scrollHeight, innerHeight } = await page.evaluate(() => ({
      scrollHeight: document.documentElement.scrollHeight,
      innerHeight: window.innerHeight,
    }));
    expect(scrollHeight).toBeLessThanOrEqual(innerHeight);
  });

  test("turning the phone keeps the whole aiming frame on screen", async ({
    page,
  }) => {
    // The frame and the region the decoder reads are sized when the camera
    // starts. Started on its side and turned upright, the phone kept the
    // landscape frame, wider than the screen and hanging off both edges.
    await page.setViewportSize({ width: 844, height: 390 });
    await page.reload();
    await openCamera(page);
    const frame = page.getByTestId("scan-aim-frame");
    await expect(frame).toBeVisible();

    await page.setViewportSize({ width: 390, height: 844 });

    await expect
      .poll(
        async () => {
          const box = await frame.boundingBox();
          return box !== null && box.x >= 0 && box.x + box.width <= 390;
        },
        { timeout: 15000 },
      )
      .toBe(true);
  });

  test("a blank frame reads nothing", async ({ page, camera }) => {
    await openCamera(page);
    await camera.hide();
    await camera.runFrames(75);
    expect(camera.scanRequests()).toEqual([]);
  });

  test("leaving the scan page after a read releases the camera", async ({
    page,
    camera,
  }) => {
    await openCamera(page);
    await camera.showEan13(UNKNOWN_EAN);
    await expect
      .poll(() => camera.scanRequests(), { timeout: 10000 })
      .toEqual([UNKNOWN_EAN]);
    // The read opens the new-product sheet over the page; put the code away
    // and close it, the way a user would before leaving.
    await camera.hide();
    const sheet = page.getByRole("dialog", { name: "New Product" });
    await sheet.getByRole("button", { name: "Cancel" }).click();
    await expect(sheet).toBeHidden();
    // Through the app's own navigation: a page load would start a new
    // document, and the fake camera's counters with it, so "nothing live"
    // would hold whatever the app did with its stream.
    await page
      .getByRole("navigation", { name: "Module navigation" })
      .getByRole("link", { name: "Overview" })
      .click();
    await expect(page).toHaveURL(/\/inventory$/);
    await expect
      .poll(() => camera.streams())
      .toMatchObject({ opened: 1, live: 0 });
    await camera.runFrames(60);
    expect(camera.scanRequests()).toEqual([UNKNOWN_EAN]);
  });

  test("a code held in view is looked up once", async ({ page, camera }) => {
    await openCamera(page);
    await camera.showEan13(UNKNOWN_EAN);
    await expect
      .poll(() => camera.scanRequests().length, { timeout: 10000 })
      .toBeGreaterThan(0);
    await camera.runFrames(120);
    expect(camera.scanRequests()).toEqual([UNKNOWN_EAN]);
  });

  test("a code held in view through a turn is looked up once", async ({
    page,
    camera,
  }) => {
    // A turn restarts the camera to size its frame for the new screen; the
    // restart forgot the code it had read, and a code still held counted again.
    // The document scan page keeps reading after a read; the item scan page
    // pauses its camera, so it would not show a second reading anyway.
    await page.goto("/warehouse/scan");
    await openCamera(page);
    await camera.showEan13(UNKNOWN_EAN);
    await expect
      .poll(() => camera.scanRequests().length, { timeout: 10000 })
      .toBeGreaterThan(0);

    await page.setViewportSize({ width: 844, height: 390 });
    await expect
      .poll(async () => (await camera.streams()).opened, { timeout: 10000 })
      .toBeGreaterThan(1);
    await camera.runFrames(150);
    expect(camera.scanRequests()).toEqual([UNKNOWN_EAN]);
  });

  test("the document scan page looks a code in view up once", async ({
    page,
    camera,
  }) => {
    await page.goto("/warehouse/scan");
    await openCamera(page);
    await camera.showEan13(UNKNOWN_EAN);
    await expect
      .poll(() => camera.scanRequests().length, { timeout: 10000 })
      .toBeGreaterThan(0);
    await camera.runFrames(120);
    expect(camera.scanRequests()).toEqual([UNKNOWN_EAN]);
  });
});

/**
 * The forms feed the same reader, so one code in front of the camera is one
 * read there too, and the camera belongs to the panel that shows it. These
 * specs drive the three form surfaces a warehouse worker scans on — the new
 * document's line workspace, the purchase order's lines, and the add-asset
 * form — through the fake camera and count what the app sent.
 */

/**
 * A valid EAN-13 no other spec uses, so parallel runs never share a record.
 * Random, not the clock: the chromium and mobile workers load this file in the
 * same millisecond, and two creates of one new barcode at once collide.
 */
function uniqueEan13(): string {
  const body = `400638${String(Math.floor(Math.random() * 1_000_000)).padStart(6, "0")}`;
  let sum = 0;
  for (let i = 0; i < 12; i++) sum += Number(body[i]) * (i % 2 === 0 ? 1 : 3);
  return body + String((10 - (sum % 10)) % 10);
}

const PRODUCT_EAN = uniqueEan13();

test.describe("Scan — one read per presence on the forms", () => {
  let api: ApiHelper;
  let token: string;
  let storageCode: string;
  let productName: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    api = new ApiHelper(await playwright.request.newContext({ baseURL }));
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;

    // Its own location: the first one of the shared tenant belongs to
    // whichever parallel spec deletes it first.
    const kitchen = (await api.createStorage(token, {
      name: `E2E-Camera-Forms-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    })) as { id: string; short_code: string };
    storageCode = kitchen.short_code;
    // A stocked record the barcode stands for: a document scan then has a
    // line to place, and the equipment form has a product to name.
    productName = `E2E-Camera-Product-${Date.now().toString(36)}`;
    await api.createItem(token, {
      name: productName,
      barcode: PRODUCT_EAN,
      quantity: 25,
      location_id: kitchen.id,
    });
  });

  /**
   * The row a scan of PRODUCT_EAN lands on, found by the product it names —
   * the form opens with its own empty line, so the index alone would be a
   * different row than the one the scan wrote.
   */
  function productRow(page: import("@playwright/test").Page) {
    return page
      .locator('[data-testid^="document-line-card-layout-"]')
      .filter({ hasText: productName });
  }

  /** The reader's picture, once the panel that holds it is open. */
  async function expectReaderVideo(page: import("@playwright/test").Page) {
    await expect(page.locator("#qr-reader video")).toBeVisible({
      timeout: 15000,
    });
  }

  /**
   * New document → the line workspace, with its scan panel open. /warehouse
   * opens History, whose "New document manually" sits under the entries and
   * moves as other workers post; the document list keeps its own "New
   * document" in the page header.
   */
  async function openDocumentScan(page: import("@playwright/test").Page) {
    await page.goto("/warehouse/all");
    await page
      .getByRole("button", { name: "New document", exact: true })
      .click();
    await page
      .getByRole("menu", { name: "New document" })
      .getByRole("menuitem", { name: /^Receipt\b/ })
      .click();
    // The switch at the bottom edge of the sheet, where a worker who has
    // scrolled the setup fields finds it — and where a retried click puts it
    // too. The camera opens under the switch, so the form has to bring it
    // into view: WebKit does not start a muted video it counts out of view,
    // and a reader out of view never gets a frame.
    const scan = page.getByRole("button", { name: "Scan", exact: true });
    await scan.evaluate((el) => el.scrollIntoView({ block: "end" }));
    await scan.click();
    await expectReaderVideo(page);
    await expect(page.locator("#qr-reader video")).toBeInViewport();
  }

  test("the document form adds one piece for a code held in view", async ({
    page,
    camera,
    authenticatedPage: _auth,
  }) => {
    test.setTimeout(90000);
    await openDocumentScan(page);

    await camera.showEan13(PRODUCT_EAN);
    await expect
      .poll(() => camera.scanRequests(), { timeout: 20000 })
      .toContain(PRODUCT_EAN);

    // One confirmation, and it says where the product went — onto this
    // document's lines, not into stock.
    await expect(
      page
        .locator("[data-sonner-toast]")
        .filter({ hasText: "to the document lines" }),
    ).toHaveCount(1);

    // Five seconds of holding the same code. Still one piece, one line
    // and one lookup: the camera read the presence, not the frames.
    await camera.runFrames(150);
    await expect(productRow(page)).toHaveCount(1);
    await expect(productRow(page).locator('[id$="-quantity"]')).toHaveValue(
      "1",
    );
    expect(camera.scanRequests()).toEqual([PRODUCT_EAN]);
  });

  test("taking the code away and showing it again adds a second piece", async ({
    page,
    camera,
    authenticatedPage: _auth,
  }) => {
    test.setTimeout(90000);
    await openDocumentScan(page);

    await camera.showEan13(PRODUCT_EAN);
    await expect
      .poll(() => camera.scanRequests(), { timeout: 20000 })
      .toHaveLength(1);

    // Out of view for a few seconds — long enough for the reader to count
    // the code gone — then shown again: a second piece, not the same read.
    await camera.hide();
    await camera.runFrames(150);
    await camera.showEan13(PRODUCT_EAN);
    await expect
      .poll(() => camera.scanRequests(), { timeout: 20000 })
      .toHaveLength(2);

    await camera.runFrames(60);
    // One product line, now two pieces: the second presence was counted,
    // and it landed on the line the first one created.
    await expect(productRow(page)).toHaveCount(1);
    await expect(productRow(page).locator('[id$="-quantity"]')).toHaveValue(
      "2",
    );
    expect(camera.scanRequests()).toEqual([PRODUCT_EAN, PRODUCT_EAN]);
  });

  test("closing the document form's panel stops the camera; reopening reads again", async ({
    page,
    camera,
    authenticatedPage: _auth,
  }) => {
    test.setTimeout(90000);
    await openDocumentScan(page);

    // A code that lands elsewhere in the app: the panel stays open, so the
    // close and the reopen can be done by hand, with the code still in view.
    await camera.showQr(storageCode);
    await expect
      .poll(() => camera.scanRequests(), { timeout: 20000 })
      .toContain(storageCode);

    // "Close" is the panel's own switch: the sheet draws its X with the same
    // accessible name, and the panel's is the later one in the document.
    await page
      .getByRole("button", { name: "Close", exact: true })
      .last()
      .click();
    await expect(page.locator("#qr-reader")).toHaveCount(0);
    await expect.poll(() => camera.streams()).toMatchObject({ live: 0 });
    const afterClose = camera.scanRequests().length;
    await camera.runFrames(120);
    expect(camera.scanRequests()).toHaveLength(afterClose);

    // Reopening starts a fresh reader: the code still in front of it is read
    // again.
    await page.getByRole("button", { name: "Scan", exact: true }).click();
    await expectReaderVideo(page);
    await expect
      .poll(() => camera.scanRequests().length, { timeout: 20000 })
      .toBe(afterClose + 1);
  });

  test("the equipment form reads a barcode once and releases the camera", async ({
    page,
    camera,
    authenticatedPage: _auth,
  }) => {
    test.setTimeout(90000);
    await page.goto("/equipment/add");
    await page.getByRole("button", { name: "Scan", exact: true }).click();
    await expectReaderVideo(page);

    await camera.showEan13(PRODUCT_EAN);
    await expect
      .poll(() => camera.scanRequests(), { timeout: 20000 })
      .toContain(PRODUCT_EAN);

    // The read fills the field, closes the panel and gives the stream back.
    await expect(page.locator("#equipment-barcode")).toHaveValue(PRODUCT_EAN);
    await expect(page.locator("#qr-reader")).toHaveCount(0);
    await expect.poll(() => camera.streams()).toMatchObject({ live: 0 });
    await camera.runFrames(120);
    expect(camera.scanRequests()).toEqual([PRODUCT_EAN]);
    // A loop of reads answered 429 and painted error toasts over the form.
    await expect(
      page.locator("[data-sonner-toast][data-type='error']"),
    ).toHaveCount(0);
  });

  test("closing the equipment scanner stops the camera; reopening reads again", async ({
    page,
    camera,
    authenticatedPage: _auth,
  }) => {
    test.setTimeout(90000);
    await page.goto("/equipment/add");
    await page.getByRole("button", { name: "Scan", exact: true }).click();
    await expectReaderVideo(page);

    await camera.showQr(storageCode);
    await expect
      .poll(() => camera.scanRequests(), { timeout: 20000 })
      .toContain(storageCode);

    await page
      .getByRole("button", { name: "Close scanner", exact: true })
      .click();
    await expect(page.locator("#qr-reader")).toHaveCount(0);
    await expect.poll(() => camera.streams()).toMatchObject({ live: 0 });
    const afterClose = camera.scanRequests().length;
    await camera.runFrames(120);
    expect(camera.scanRequests()).toHaveLength(afterClose);

    await page.getByRole("button", { name: "Scan", exact: true }).click();
    await expectReaderVideo(page);
    await expect
      .poll(() => camera.scanRequests().length, { timeout: 20000 })
      .toBe(afterClose + 1);
  });

  test("the purchase-order form reads one lookup per code in view", async ({
    page,
    camera,
    authenticatedPage: _auth,
  }) => {
    test.setTimeout(90000);
    await page.goto("/purchase-orders");
    // Two "Create order" buttons exist on an empty list — the header's and
    // the empty state's; either opens the same form.
    await page
      .getByRole("button", { name: "Create order", exact: true })
      .first()
      .click();
    await expect(
      page.getByRole("heading", { name: "New purchase order" }),
    ).toBeVisible({ timeout: 15000 });
    await page.getByRole("button", { name: "Scan", exact: true }).click();
    await expectReaderVideo(page);

    await camera.showQr(storageCode);
    await expect
      .poll(() => camera.scanRequests(), { timeout: 20000 })
      .toContain(storageCode);

    await camera.runFrames(120);
    expect(camera.scanRequests()).toEqual([storageCode]);

    // And the panel, not the wish to scan, owns the camera: closing it by
    // hand stops the reads until it is opened again.
    await page
      .getByRole("button", { name: "Close scanner", exact: true })
      .click();
    await expect(page.locator("#qr-reader")).toHaveCount(0);
    await expect.poll(() => camera.streams()).toMatchObject({ live: 0 });
    const afterClose = camera.scanRequests().length;
    await camera.runFrames(120);
    expect(camera.scanRequests()).toHaveLength(afterClose);

    await page.getByRole("button", { name: "Scan", exact: true }).click();
    await expectReaderVideo(page);
    await expect
      .poll(() => camera.scanRequests().length, { timeout: 20000 })
      .toBe(afterClose + 1);
  });
});

test.describe("Scan — execution reads one presence", () => {
  let api: ApiHelper;
  let token: string;
  let locationId: string;
  let partnerId: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    api = new ApiHelper(await playwright.request.newContext({ baseURL }));
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
    // Its own location, as above.
    locationId = (
      await api.createStorage(token, {
        name: `E2E-Camera-Execution-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      })
    ).id;
    const partner = await api.createPartner(token, {
      name: `E2E-Camera-Customer-${crypto.randomUUID()}`,
      type: "CUSTOMER",
    });
    partnerId = partner.id;
  });

  /**
   * A confirmed goods issue with one planned line for its own barcode,
   * opened in its execution panel with scan mode on and the camera running.
   */
  async function openExecutionScan(
    page: import("@playwright/test").Page,
    expectedQuantity: number,
  ) {
    const ean = uniqueEan13();
    const item = await api.createItem(token, {
      name: `E2E-Camera-Exec-${Date.now().toString(36)}`,
      barcode: ean,
      quantity: expectedQuantity,
      location_id: locationId,
    });
    const doc = await api.createDocument(token, {
      type: "OUT",
      source_location_id: locationId,
      partner_id: partnerId,
      lines: [
        {
          item_id: item.id,
          barcode: ean,
          expected_quantity: expectedQuantity,
        },
      ],
    });
    await api.confirmDocument(token, doc.id);
    const full = await api.getDocument(token, doc.id);
    const lineId = (full.lines as Array<{ id: string }>)[0].id;

    await page.goto(`/warehouse/documents/${doc.id}`);
    await page.getByRole("button", { name: "Pick items" }).click();
    await expect(
      page.getByRole("heading", { name: "Execute document" }),
    ).toBeVisible({ timeout: 15000 });
    await page.getByRole("button", { name: "Scan mode", exact: true }).click();
    await page
      .getByRole("button", { name: "Open camera", exact: true })
      .click();
    await expect(page.locator("#qr-reader video")).toBeVisible({
      timeout: 15000,
    });
    return { lineId, ean };
  }

  test("a code held in view books one unit, not the planned quantity", async ({
    page,
    camera,
    authenticatedPage: _auth,
  }) => {
    test.setTimeout(120000);
    const { lineId, ean } = await openExecutionScan(page, 10);

    await camera.showEan13(ean);
    const done = page.locator(`#done-quantity-${lineId}`);
    await expect(done).toHaveValue("1", { timeout: 20000 });

    // Eight seconds of holding the same code: still one unit. Taking it away
    // and showing it again is how a worker books the next one.
    await camera.runFrames(240);
    await expect(done).toHaveValue("1");
  });

  test("a code that is not on the document is looked up once", async ({
    page,
    camera,
    authenticatedPage: _auth,
  }) => {
    test.setTimeout(120000);
    await openExecutionScan(page, 10);

    // A second, valid EAN the document does not carry.
    const foreign = uniqueEan13();
    await camera.showEan13(foreign);
    await expect
      .poll(() => camera.scanRequests(), { timeout: 20000 })
      .toContain(foreign);
    await camera.runFrames(120);
    expect(camera.scanRequests()).toEqual([foreign]);
  });
});
