import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * Receiving through the UI, measured where it is supposed to land.
 *
 * Every other document spec stops at the screen: it checks that a button is
 * there, that a status badge changed, that a toast appeared. None of them
 * followed a receipt all the way into StockQuant, so a receiving that drew
 * the right screen and moved nothing would have passed the suite. This spec
 * drives the inbound path a warehouse worker actually uses — open the
 * confirmed document, enter what arrived, close it — and then reads the
 * stock ledger.
 */

const RECEIVED = 7;

test.describe("Documents — receiving reaches the stock ledger", () => {
  let api: ApiHelper;
  let token: string;
  let locationId: string;
  let templateId: string;
  let partnerId: string;

  test.beforeAll(async ({ playwright, baseURL }, testInfo) => {
    // A stamp of this setup's own, not of the file's load: the file runs
    // fully parallel, so a worker that comes back to it runs this setup
    // again, and a stamp taken once at load met its own supplier from the
    // first time with PARTNER_CONFLICT.
    const UID = `${Date.now().toString(36)}-w${testInfo.workerIndex}`;
    const ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    const auth = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = auth.access_token;
    await api.enableAllModules(token);

    const storage = await api.createStorageIdempotent(token, {
      name: `E2E-Receiving-${UID}`,
      location_type: "SHELF",
    });
    locationId = storage.id;

    const template = await api.createProductTemplate(token, {
      name: `E2E-Receiving-Widget-${UID}`,
    });
    templateId = template.id;

    // IN documents require a partner (backend rule), so the fixture needs one.
    const partner = await api.createPartner(token, {
      name: `E2E-Receiving-Supplier-${UID}`,
      type: "SUPPLIER",
    });
    partnerId = partner.id;
  });

  test("receiving a confirmed IN document adds the received quantity to stock", async ({
    page,
    authenticatedPage,
  }) => {
    const before = await api.quantityOnHand(token, templateId, locationId);

    const doc = await api.createDocument(token, {
      type: "IN",
      partner_id: partnerId,
      target_location_id: locationId,
      lines: [{ product_template_id: templateId, expected_quantity: RECEIVED }],
    });
    await api.confirmDocument(token, doc.id);
    // Confirmation allocates the final number (DRAFT-… becomes IN/…), so the
    // heading carries what the document is called now, not at creation.
    const confirmed = await api.getDocument(token, doc.id);

    await page.goto(`/warehouse/documents/${doc.id}`);
    await expect(
      page.getByRole("heading", { name: String(confirmed.number) }),
    ).toBeVisible({
      timeout: 15000,
    });

    // "Receive stock" is the inbound execute — distinct from "Scan receiving",
    // which opens the barcode session.
    await page.getByRole("button", { name: "Receive stock" }).click();
    await expect(
      page.getByRole("heading", { name: "Execute document" }),
    ).toBeVisible();

    // The quantity that actually arrived. Typing it is the path a worker
    // takes when the delivery does not match the order; "Fill remaining" is
    // the shortcut for when it does.
    const quantityField = page.getByLabel("Executed quantity");
    await quantityField.fill(String(RECEIVED));

    await page.getByRole("button", { name: "Confirm & complete" }).click();
    await expect(
      page.getByText("Document completed — stock updated"),
    ).toBeVisible({ timeout: 15000 });

    // The point of the whole exercise: the ledger moved, by exactly the
    // quantity that was entered.
    await expect
      .poll(() => api.quantityOnHand(token, templateId, locationId), {
        timeout: 15000,
      })
      .toBe(before + RECEIVED);

    // And the document says so too, rather than sitting in CONFIRMED with the
    // stock already moved.
    const reread = await api.getDocument(token, doc.id);
    expect(reread.status).toBe("COMPLETED");
  });

  test("a short receipt moves only what arrived", async ({
    page,
    authenticatedPage,
  }) => {
    const before = await api.quantityOnHand(token, templateId, locationId);
    const arrived = 3;

    const doc = await api.createDocument(token, {
      type: "IN",
      partner_id: partnerId,
      target_location_id: locationId,
      lines: [{ product_template_id: templateId, expected_quantity: RECEIVED }],
    });
    await api.confirmDocument(token, doc.id);
    const confirmed = await api.getDocument(token, doc.id);

    await page.goto(`/warehouse/documents/${doc.id}`);
    await expect(
      page.getByRole("heading", { name: String(confirmed.number) }),
    ).toBeVisible({
      timeout: 15000,
    });
    await page.getByRole("button", { name: "Receive stock" }).click();
    await page.getByLabel("Executed quantity").fill(String(arrived));

    // Receiving less than ordered is a discrepancy, and the form requires it
    // to be named before it will close the document.
    await page
      .getByLabel("Discrepancy code")
      .selectOption({ label: "Shortage" });

    await page.getByRole("button", { name: "Confirm & complete" }).click();
    await expect(page.getByText("Document completed")).toBeVisible({
      timeout: 15000,
    });

    await expect
      .poll(() => api.quantityOnHand(token, templateId, locationId), {
        timeout: 15000,
      })
      .toBe(before + arrived);
  });
});
