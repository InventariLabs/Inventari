import type { APIRequestContext } from "@playwright/test";
import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * The guide's example module, through the screens a warehouse worker uses.
 *
 * `examples/lot_certificates` adds a certificate number to every received
 * lot, refuses to book a receipt whose certificate is not on file, walks a
 * pick zone by zone with the heaviest line first, and puts a certificate
 * column, a filter and an action on the documents. The backend suite proves
 * each seam through the API; this walks receive → confirm → pick in the
 * browser with the module enabled, so a seam whose screen half broke shows
 * up too.
 *
 * The module must be installed in the stack under test, which no other spec
 * needs, so this one is its own project, present only with
 * E2E_EXAMPLE_MODULE=1: `make e2e-example-module` installs the module, runs
 * this spec and uninstalls it again.
 */

const UID = Date.now().toString(36);
const MODULE = "lot_certificates";
const LOT = `LOT-${UID}`;
const CERTIFICATE = `C-${UID}`;

test.describe.configure({ mode: "serial" });

test.describe("The example module extends the warehouse", () => {
  let ctx: APIRequestContext;
  let api: ApiHelper;
  let token: string;
  let previousStrategy: string | null = null;
  let supplierId: string;
  let customerId: string;
  let warehouseId: string;
  const shelves: Record<string, string> = {};

  const headers = () => ({ Authorization: `Bearer ${token}` });

  async function location(
    name: string,
    parent: string | null,
    sequence: number,
  ): Promise<string> {
    const created = await api.createStorage(token, {
      name: `${name}-${UID}`,
      location_type: parent ? "SHELF" : "WAREHOUSE",
      ...(parent && { parent_id: parent }),
      sequence,
    });
    return created.id;
  }

  /** A product with its weight, standing on one shelf. */
  async function stock(
    name: string,
    shelf: string,
    weight: string,
  ): Promise<{ id: string; template_id: string }> {
    const response = await ctx.post("/api/v1/items", {
      headers: headers(),
      data: {
        name: `${name}-${UID}`,
        quantity: 10,
        location_id: shelf,
        weight_value: weight,
      },
    });
    expect(response.ok(), await response.text()).toBeTruthy();
    return await response.json();
  }

  test.beforeAll(async ({ playwright, baseURL }) => {
    ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
    await api.toggleModule(token, "warehouse", true);
    await api.toggleModule(token, MODULE, true);

    const profile = await ctx.get("/api/v1/warehouse/profile", {
      headers: headers(),
    });
    previousStrategy = (await profile.json()).pick_order_strategy ?? null;
    const chosen = await ctx.put("/api/v1/warehouse/profile", {
      headers: headers(),
      data: { pick_order_strategy: "by_zone_then_weight" },
    });
    expect(chosen.ok(), await chosen.text()).toBeTruthy();

    supplierId = (
      await api.createPartner(token, {
        name: `E2E-Certified-Supplier-${UID}`,
        type: "SUPPLIER",
      })
    ).id;
    customerId = (
      await api.createPartner(token, {
        name: `E2E-Certified-Customer-${UID}`,
        type: "CUSTOMER",
      })
    ).id;

    // Two zones walked in their numbered order; inside zone A the light
    // product's shelf comes first, so the default walk would take it first.
    warehouseId = await location("E2E-Cert-Warehouse", null, 1);
    const zoneA = await location("Zone-A", warehouseId, 1);
    const zoneB = await location("Zone-B", warehouseId, 2);
    shelves.a1 = await location("A1", zoneA, 1);
    shelves.a2 = await location("A2", zoneA, 2);
    shelves.b1 = await location("B1", zoneB, 1);
  });

  test.afterAll(async () => {
    await ctx.put("/api/v1/warehouse/profile", {
      headers: headers(),
      data: { pick_order_strategy: previousStrategy },
    });
    await api.toggleModule(token, MODULE, false);
    await ctx.dispose();
  });

  test("a lot is received only with its certificate, and only once it is on file", async ({
    page,
    authenticatedPage,
  }) => {
    void authenticatedPage;
    const washers = await stock("Washers", shelves.a1, "0.2");
    const doc = await api.createDocument(token, {
      type: "IN",
      partner_id: supplierId,
      target_location_id: shelves.a1,
      lines: [
        {
          product_template_id: washers.template_id,
          expected_quantity: 5,
          batch_number: LOT,
        },
      ],
    });

    await page.goto(`/warehouse/documents/${doc.id}`);
    // Receiving a draft confirms and books it in one press; the module is
    // asked at both stages, inside one transaction.
    const receive = async () => {
      await page.getByRole("button", { name: "Receive stock" }).click();
      await page.getByRole("button", { name: "Post", exact: true }).click();
    };

    // The required field: refused at the confirmation, in the module's words.
    await receive();
    await expect(
      page.getByText(`Enter the certificate number for lot ${LOT}.`),
    ).toBeVisible();

    // The module's field under the line, on the document page (the table and
    // the phone's cards both carry it; the role query sees the one shown).
    await page
      .getByRole("textbox", { name: `Certificate for lot ${LOT}` })
      .fill(CERTIFICATE);
    await page.getByRole("button", { name: "Save certificate" }).click();
    await expect(
      page.getByRole("button", { name: "Save certificate" }),
    ).toBeDisabled();

    // The receiving rule: not booked while the certificate is not on file.
    await receive();
    await expect(
      page.getByText(`Certificate ${CERTIFICATE} is not on file.`, {
        exact: false,
      }),
    ).toBeVisible();
    expect((await api.getDocument(token, doc.id)).status).toBe("DRAFT");

    // The module's action on the document's row files it.
    await page.getByRole("button", { name: "File the certificates" }).click();
    await expect(page.getByText("The certificates are on file.")).toBeVisible();

    await receive();
    await expect
      .poll(async () => (await api.getDocument(token, doc.id)).status, {
        timeout: 15000,
      })
      .toBe("COMPLETED");

    // The register: the module's column and its filter on History.
    const posted = await api.getDocument(token, doc.id);
    await page.goto("/warehouse/history");
    await page.getByRole("button", { name: "Certified lots" }).click();
    const row = page
      .getByRole("listitem")
      .filter({ has: page.getByRole("link", { name: String(posted.number) }) });
    await expect(row).toBeVisible();
    await expect(row.getByText("Certificate", { exact: true })).toBeVisible();
    await expect(row.getByText(CERTIFICATE)).toBeVisible();

    // And on the full Documents list, whose filter sits in its panel.
    await page.goto("/warehouse/all");
    await page
      .getByRole("button", { name: /Filter/ })
      .first()
      .click();
    await page.getByRole("button", { name: "Certified lots" }).first().click();
    await expect(
      page.getByRole("button", { name: String(posted.number) }),
    ).toBeVisible();
    await expect(page.getByText(CERTIFICATE)).toBeVisible();
  });

  test("a certificate on file with its spaces stays the same number on the document page", async ({
    page,
    authenticatedPage,
  }) => {
    void authenticatedPage;
    // A number is read as written, spaces included, by the receiving rule,
    // the register and the filter; the page's editor must not tidy it into
    // another number that is not on file.
    const padded = ` P-${UID} `;
    const lot = `LOT-P-${UID}`;
    const bolts = await stock("Padded-Bolts", shelves.b1, "1");
    const filed = await ctx.post("/api/v1/lot-certificates/certificates", {
      headers: headers(),
      data: { numbers: [padded] },
    });
    expect(filed.ok(), await filed.text()).toBeTruthy();
    const doc = await api.createDocument(token, {
      type: "IN",
      partner_id: supplierId,
      target_location_id: shelves.b1,
      lines: [
        {
          product_template_id: bolts.template_id,
          expected_quantity: 2,
          batch_number: lot,
          meta_data: { [MODULE]: { number: padded } },
        },
      ],
    });

    await page.goto(`/warehouse/documents/${doc.id}`);
    await expect(
      page.getByRole("textbox", { name: `Certificate for lot ${lot}` }),
    ).toHaveValue(padded);
    // Nothing was changed, so there is nothing to save.
    await expect(
      page.getByRole("button", { name: "Save certificate" }),
    ).toBeDisabled();

    await page.getByRole("button", { name: "Receive stock" }).click();
    await page.getByRole("button", { name: "Post", exact: true }).click();
    await expect
      .poll(async () => (await api.getDocument(token, doc.id)).status, {
        timeout: 15000,
      })
      .toBe("COMPLETED");
  });

  test("a pick walks zone by zone, the heaviest line of each zone first", async ({
    page,
    authenticatedPage,
  }) => {
    void authenticatedPage;
    const washers = await stock("Pick-Washers", shelves.a1, "0.2");
    const anvils = await stock("Pick-Anvils", shelves.a2, "12");
    const bolts = await stock("Pick-Bolts", shelves.b1, "1");
    const doc = await api.createDocument(token, {
      type: "OUT",
      partner_id: customerId,
      source_location_id: warehouseId,
      lines: [washers, bolts, anvils].map((item) => ({
        item_id: item.id,
        product_template_id: item.template_id,
        expected_quantity: 1,
      })),
    });
    await api.confirmDocument(token, doc.id);

    await page.goto(`/warehouse/documents/${doc.id}`);
    await page.getByRole("button", { name: "Scan picking" }).click();
    const sheet = page.getByRole("dialog");
    await expect(sheet.getByText(`Pick-Bolts-${UID}`)).toBeVisible({
      timeout: 15000,
    });

    const text = (await sheet.innerText()).toString();
    const order = ["Pick-Anvils", "Pick-Washers", "Pick-Bolts"].map((name) =>
      text.indexOf(`${name}-${UID}`),
    );
    // Zone A first, its 12 kg anvils before its washers; then zone B.
    expect(order.every((at) => at >= 0)).toBeTruthy();
    expect([...order].sort((a, b) => a - b)).toEqual(order);
  });
});
