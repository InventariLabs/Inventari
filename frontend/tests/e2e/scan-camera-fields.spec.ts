import { test, expect } from "./fixtures/camera";
import { startSeed } from "./helpers/receive-seed";

// A phone held upright, as in scan-camera.spec.ts: the reader's crop is
// computed for it, and reads are measured in Chromium only.
test.use({ viewport: { width: 390, height: 844 } });

const NO_READS_IN_WEBKIT =
  "camera reads are measured in Chromium; Linux WebKit stalls the fake camera's video";

/** Page errors the reader's canvas raised while a camera was closing. */
function watchCanvasErrors(page: import("@playwright/test").Page) {
  const raised: string[] = [];
  page.on("pageerror", (error) => {
    if (/getImageData/.test(error.message)) raised.push(error.message);
  });
  return raised;
}

// A valid EAN-13 of its own: the field takes whatever the camera reads.
const PRODUCT_CODE = "4006381333931";

/**
 * The camera that fills a field of a form — here the product's barcode — is
 * the same reader as the scan page's, put away after one read. Measured in
 * the browser: the code lands in the field, the camera is given back (no
 * stream left live), and the torch button follows what the camera reports.
 */
test.describe("Camera field entry — the product code", () => {
  test.beforeEach(async ({ page, camera: _camera, browserName }) => {
    test.skip(browserName === "webkit", NO_READS_IN_WEBKIT);
    await page.goto("/inventory/items/add");
  });

  test("a read fills the barcode field and gives the camera back", async ({
    page,
    camera,
  }) => {
    const canvasErrors = watchCanvasErrors(page);
    await page.getByRole("button", { name: "Scan product code" }).click();
    await expect(page.locator("#qr-reader video")).toBeVisible({
      timeout: 15000,
    });

    await camera.showEan13(PRODUCT_CODE);

    await expect(
      page.getByRole("textbox", { name: "Product code" }),
    ).toHaveValue(PRODUCT_CODE, {
      timeout: 20000,
    });
    await expect(page.locator("#qr-reader")).toHaveCount(0);
    await expect.poll(async () => (await camera.streams()).live).toBe(0);
    expect(canvasErrors).toEqual([]);
  });

  test("closing the camera without a read releases it and leaves the field alone", async ({
    page,
    camera,
  }) => {
    const canvasErrors = watchCanvasErrors(page);
    await page.getByRole("button", { name: "Scan product code" }).click();
    await expect(page.locator("#qr-reader video")).toBeVisible({
      timeout: 15000,
    });

    await page.getByRole("button", { name: "Close camera" }).click();

    await expect(page.locator("#qr-reader")).toHaveCount(0);
    await expect.poll(async () => (await camera.streams()).live).toBe(0);
    await expect(
      page.getByRole("textbox", { name: "Product code" }),
    ).toHaveValue("");
    await camera.runFrames(15);
    expect(canvasErrors).toEqual([]);
  });

  test("offers the light only when the camera has one", async ({
    page,
    camera,
  }) => {
    await page.getByRole("button", { name: "Scan product code" }).click();
    await expect(page.locator("#qr-reader video")).toBeVisible({
      timeout: 15000,
    });
    await expect(
      page.getByRole("button", { name: "Turn the light on" }),
    ).toHaveCount(0);
    await page.getByRole("button", { name: "Close camera" }).click();

    await camera.setTorch(true);
    await page.getByRole("button", { name: "Scan product code" }).click();

    await expect(
      page.getByRole("button", { name: "Turn the light on" }),
    ).toBeVisible({ timeout: 15000 });
  });
});

/**
 * The lot of a product taken by earliest expiry is asked for when it is
 * scanned into a receiving session, and the code printed on the pack is read
 * with the camera instead of typed. The question's sheet opens on its own
 * heading — not on the lot box, which would raise a phone's keyboard over the
 * viewfinder the reader needs — and the camera goes back once the lot is read.
 */
test.describe("Camera field entry — the lot code", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("a read fills the lot, the sheet opens on its heading, and the camera is given back", async ({
    page,
    camera,
    playwright,
    baseURL,
    browserName,
  }, testInfo) => {
    test.skip(browserName === "webkit", NO_READS_IN_WEBKIT);
    const canvasErrors = watchCanvasErrors(page);
    const seed = await startSeed({ playwright }, baseURL, testInfo);
    const shelf = await seed.shelf("Shelf");
    const supplier = await seed.partner("Supplier", "SUPPLIER");
    const yoghurt = await seed.product("Yoghurt", true);
    const doc = await seed.api.createDocument(seed.token, {
      type: "IN",
      partner_id: supplier.id,
      target_location_id: shelf.id,
      lines: [{ product_template_id: yoghurt.id, expected_quantity: 4 }],
    });
    await seed.api.confirmDocument(seed.token, doc.id);

    await page.goto(`/warehouse/documents/${doc.id}`);
    await page.getByRole("button", { name: "Scan receiving" }).click();
    const scanField = page.getByPlaceholder("Scan product barcode…");
    await expect(scanField).toBeVisible();
    await scanField.fill(yoghurt.barcode);
    await scanField.press("Enter");

    const sheet = page.getByRole("dialog", { name: "Lot and expiry" });
    await expect(sheet).toBeVisible({ timeout: 15000 });
    await expect(
      sheet.getByRole("heading", { name: "Lot and expiry" }),
    ).toBeFocused();
    await expect(sheet.getByRole("textbox", { name: "Lot" })).not.toBeFocused();

    await sheet.getByRole("button", { name: "Scan lot code" }).click();
    await expect(page.locator("#qr-reader video")).toBeVisible({
      timeout: 15000,
    });
    await camera.showQr("FLOOR-LOT-5884");

    await expect(sheet.getByRole("textbox", { name: "Lot" })).toHaveValue(
      "FLOOR-LOT-5884",
      { timeout: 20000 },
    );
    await expect(page.locator("#qr-reader")).toHaveCount(0);
    await expect.poll(async () => (await camera.streams()).live).toBe(0);
    expect(canvasErrors).toEqual([]);
  });
});
