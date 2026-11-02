import { type Page } from "@playwright/test";
import { test, expect } from "./fixtures/auth";
import {
  startSeed,
  type ReceivingSeed,
  type SeededPartner,
  type SeededProduct,
  type SeededShelf,
} from "./helpers/receive-seed";
import {
  arrivedField,
  chooseLocation,
  choosePartner,
  chooseSource,
  openReceive,
  scanProduct,
  scanShelf,
  session,
  type Source,
} from "./helpers/receive-screen";

/**
 * "Where do the goods come from?" on the Receive screen, on a desk and on a
 * phone.
 *
 * The three answers write different documents: a supplier's delivery and a
 * customer's return are both receipts (IN) that name the partner in the
 * matching role, an internal receipt (INTERNAL_IN) names nobody. Changing the
 * answer on a sheet that is already being filled must take away what belonged
 * to the old one — the partner, the order's lines — and leave the goods in
 * the worker's hands and the place they go to. Pressing the answer that is
 * already chosen is not a change and must not cost the worker the count.
 *
 * Every post is read back through the API: the document's type and partner,
 * and the shelf.
 */

const VIEWPORTS = {
  desktop: { width: 1280, height: 800 },
  phone: { width: 390, height: 844 },
} as const;

type ViewportName = keyof typeof VIEWPORTS;

const POST_LABEL: Record<Source, string> = {
  supplier: "Receive into stock",
  return: "Receive the return",
  internal: "Add to stock",
};

const DOCUMENT_TYPE: Record<Source, string> = {
  supplier: "IN",
  return: "IN",
  internal: "INTERNAL_IN",
};

interface Scene {
  seed: ReceivingSeed;
  shelf: SeededShelf;
  supplier: SeededPartner;
  customer: SeededPartner;
  rice: SeededProduct;
  beans: SeededProduct;
}

async function scene(seed: ReceivingSeed): Promise<Scene> {
  return {
    seed,
    shelf: await seed.shelf("Shelf"),
    supplier: await seed.partner("Supplier", "SUPPLIER"),
    customer: await seed.partner("Customer", "CUSTOMER"),
    rice: await seed.product("Rice"),
    beans: await seed.product("Beans"),
  };
}

/**
 * Press the post button of the open source. A desk posts the sheet; a phone
 * saves it as a receipt and walks it in the receiving session, which posts
 * on the last card.
 */
async function postOneLine(
  page: Page,
  viewport: ViewportName,
  source: Source,
  s: Scene,
) {
  if (viewport === "desktop") {
    await page.getByRole("button", { name: POST_LABEL[source] }).click();
    await expect(
      page.getByRole("heading", { name: /^Received \d+ lines?$/ }),
    ).toBeVisible({ timeout: 15000 });
    return page;
  }
  await page
    .getByRole("button", { name: "Receive one product at a time" })
    .click();
  await expect(page).toHaveURL(/#receive/);
  await scanShelf(page, s.shelf.code, { confirmed: false });
  await session(page)
    .getByRole("button", { name: "Correct, finish receiving" })
    .click();
  const dialog = session(page);
  await expect(
    dialog.getByRole("heading", { name: /^Received \d+ lines?$/ }),
  ).toBeVisible({ timeout: 15000 });
  return dialog;
}

for (const viewport of Object.keys(VIEWPORTS) as ViewportName[]) {
  test.describe(`Receive source — ${viewport}`, () => {
    test.use({
      viewport: VIEWPORTS[viewport],
      hasTouch: viewport === "phone",
      isMobile: viewport === "phone",
    });

    for (const source of ["supplier", "return", "internal"] as Source[]) {
      test(`${source}: posts ${DOCUMENT_TYPE[source]} ${
        source === "internal"
          ? "with no partner"
          : "with the matching partner role"
      }`, async ({
        page,
        playwright,
        baseURL,
        authenticatedPage: _auth,
      }, testInfo) => {
        const seed = await startSeed({ playwright }, baseURL, testInfo);
        const s = await scene(seed);

        await openReceive(page);
        if (source !== "supplier") await chooseSource(page, source);
        if (source === "internal") {
          // Nobody outside the company is named.
          await expect(
            page.getByRole("combobox", { name: "From" }),
          ).toHaveCount(0);
        } else {
          await choosePartner(
            page,
            source === "return" ? s.customer.name : s.supplier.name,
            source,
          );
        }
        await chooseLocation(page, s.shelf.name);
        await scanProduct(page, s.rice.barcode, s.rice.name);
        await arrivedField(page, s.rice.name).fill("4");

        const result = await postOneLine(page, viewport, source, s);
        const document = await seed.documentLinkedFrom(result);

        expect(document.type).toBe(DOCUMENT_TYPE[source]);
        const partner = await seed.partnerOf(document);
        if (source === "internal") {
          expect(partner).toBeNull();
        } else {
          expect(partner).toEqual({
            id: (source === "return" ? s.customer : s.supplier).id,
            type: source === "return" ? "CUSTOMER" : "SUPPLIER",
          });
        }
        expect(await seed.onHand(s.rice, s.shelf)).toBe(4);
      });
    }

    test("changing the source takes away the partner and the order, and keeps the goods and the place", async ({
      page,
      playwright,
      baseURL,
      authenticatedPage: _auth,
    }, testInfo) => {
      const seed = await startSeed({ playwright }, baseURL, testInfo);
      const s = await scene(seed);
      const order = await seed.order(s.supplier, [
        { product: s.rice, quantity: 5 },
      ]);
      const orderNote = `${order.number} expects 1 line.`;

      await openReceive(page);
      await choosePartner(page, s.supplier.name);
      await chooseLocation(page, s.shelf.name);
      await expect(page.getByText(orderNote, { exact: false })).toBeVisible();
      await page
        .getByLabel("Supplier's document number")
        .fill(`FV-${seed.uid}`);

      if (viewport === "desktop") {
        // The order's line is on the sheet; the worker adds one of their own.
        await expect(arrivedField(page, s.rice.name)).toHaveValue("5");
        await scanProduct(page, s.beans.barcode, s.beans.name);
        await arrivedField(page, s.beans.name).fill("2");
      }

      // A customer's return: the partner and the order belonged to the supplier.
      await chooseSource(page, "return");
      await expect(page.getByRole("combobox", { name: "From" })).toContainText(
        "Choose the customer",
      );
      await expect(page.getByText(order.number)).toHaveCount(0);
      await expect(
        page.getByRole("combobox", { name: "To location" }),
      ).toContainText(s.shelf.name);
      if (viewport === "desktop") {
        await expect(arrivedField(page, s.rice.name)).toHaveCount(0);
        await expect(arrivedField(page, s.beans.name)).toHaveValue("2");
      } else {
        // With no order the phone takes the goods in itself.
        await scanProduct(page, s.beans.barcode, s.beans.name);
        // The count is typed: the stepper's step depends on a unit the card
        // may not have read yet, and one run in a few moved it by 0.001.
        await arrivedField(page, s.beans.name).fill("2");
        await expect(arrivedField(page, s.beans.name)).toHaveValue("2");
      }

      // An internal receipt: no partner at all, and the goods still there.
      await chooseSource(page, "internal");
      await expect(page.getByRole("combobox", { name: "From" })).toHaveCount(0);
      await expect(
        page.getByRole("combobox", { name: "To location" }),
      ).toContainText(s.shelf.name);
      await expect(arrivedField(page, s.beans.name)).toHaveValue("2");

      // Back to a supplier: nobody is chosen, and the order is not reloaded
      // until the supplier is.
      await chooseSource(page, "supplier");
      await expect(page.getByRole("combobox", { name: "From" })).toContainText(
        "Choose the supplier",
      );
      await expect(page.getByText(order.number)).toHaveCount(0);
      await expect(arrivedField(page, s.beans.name)).toHaveValue("2");
      await expect(
        page.getByRole("combobox", { name: "To location" }),
      ).toContainText(s.shelf.name);
      // The supplier's document number was a field of a receipt that has
      // been through an internal one: it is not carried over.
      await expect(page.getByLabel("Supplier's document number")).toHaveValue(
        "",
      );
    });

    test("pressing the source that is already chosen keeps the receipt being counted", async ({
      page,
      playwright,
      baseURL,
      authenticatedPage: _auth,
    }, testInfo) => {
      const seed = await startSeed({ playwright }, baseURL, testInfo);
      const s = await scene(seed);

      for (const source of ["supplier", "return"] as const) {
        const partner = source === "return" ? s.customer : s.supplier;
        const reference = `REF-${source}-${seed.uid}`;
        await openReceive(page);
        if (source === "return") await chooseSource(page, "return");
        await choosePartner(page, partner.name, source);
        await chooseLocation(page, s.shelf.name);
        await page
          .getByLabel(
            source === "return"
              ? "Customer's document number"
              : "Supplier's document number",
          )
          .fill(reference);
        await scanProduct(page, s.rice.barcode, s.rice.name);
        await arrivedField(page, s.rice.name).fill("7");

        // The same answer again — a tap on the radio that is already on.
        await chooseSource(page, source);

        await expect(
          page.getByRole("combobox", { name: "From" }),
        ).toContainText(partner.name);
        await expect(
          page.getByRole("combobox", { name: "To location" }),
        ).toContainText(s.shelf.name);
        await expect(
          page.getByLabel(
            source === "return"
              ? "Customer's document number"
              : "Supplier's document number",
          ),
        ).toHaveValue(reference);
        await expect(arrivedField(page, s.rice.name)).toHaveValue("7");
      }
    });
  });
}

// Choosing the supplier that is already chosen, in the supplier picker, leaves
// the receipt as it is: the order's lines stay.
test.describe("Receive source — desktop", () => {
  test.use({ viewport: VIEWPORTS.desktop });

  test("choosing the same supplier again keeps the order's lines", async ({
    page,
    playwright,
    baseURL,
    authenticatedPage: _auth,
  }, testInfo) => {
    const seed = await startSeed({ playwright }, baseURL, testInfo);
    const s = await scene(seed);
    const order = await seed.order(s.supplier, [
      { product: s.rice, quantity: 5 },
    ]);

    await openReceive(page);
    await choosePartner(page, s.supplier.name);
    await expect(
      page.getByText(`${order.number} expects 1 line. It is loaded below.`),
    ).toBeVisible();
    await expect(arrivedField(page, s.rice.name)).toHaveValue("5");

    await choosePartner(page, s.supplier.name);
    await expect(arrivedField(page, s.rice.name)).toHaveValue("5");
  });
});
