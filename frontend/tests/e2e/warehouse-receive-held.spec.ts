import { test, expect } from "./fixtures/auth";
import { startSeed } from "./helpers/receive-seed";
import {
  arrivedField,
  chooseLocation,
  choosePartner,
} from "./helpers/receive-screen";

/**
 * Goods that arrive damaged are received on the one-screen Receive without
 * leaving the order waiting for them.
 *
 * Twenty were ordered and twenty came, two of them crushed. The row says so
 * in "Damaged or on hold": the two go to the quarantine location, eighteen
 * are stock to use, and the order counts the whole delivery — the two wait
 * for a decision, not for the supplier. Read back through the API: stock on
 * both places and the order.
 */
test.use({ viewport: { width: 1280, height: 800 } });

test("damaged goods go to quarantine and the order stops waiting for them", async ({
  page,
  playwright,
  baseURL,
  authenticatedPage: _auth,
}, testInfo) => {
  const seed = await startSeed({ playwright }, baseURL, testInfo);
  const shelf = await seed.shelf("Shelf");
  const quarantine = await seed.shelf("Quarantine");
  const supplier = await seed.partner("Supplier", "SUPPLIER");
  const coffee = await seed.product("Coffee");
  const order = await seed.order(supplier, [{ product: coffee, quantity: 20 }]);
  const named = await seed.request.put("/api/v1/warehouse/profile", {
    headers: { Authorization: `Bearer ${seed.token}` },
    data: { quarantine_location_id: quarantine.id },
  });
  expect(named.ok()).toBe(true);

  await page.goto("/warehouse/receive");
  await choosePartner(page, supplier.name);
  await chooseLocation(page, shelf.name);
  await expect(arrivedField(page, coffee.name)).toHaveValue("20");

  await page.getByRole("button", { name: "Damaged or on hold" }).click();
  await page
    .getByRole("textbox", { name: `Damaged or on hold: ${coffee.name}` })
    .fill("2");
  await expect(page.getByLabel("Why")).toHaveValue("DAMAGE");
  await page.getByRole("button", { name: "Receive into stock" }).click();
  await expect(
    page.getByRole("heading", { name: /^Received \d+ lines?$/ }),
  ).toBeVisible({ timeout: 15000 });

  expect(await seed.onHand(coffee, shelf)).toBe(18);
  expect(await seed.onHand(coffee, quarantine)).toBe(2);
  const document = await seed.documentLinkedFrom(page);
  expect(document.lines).toMatchObject([
    { held_quantity: "2.000", discrepancy_code: "DAMAGE" },
  ]);
  expect((await seed.orderLines(order)).map((l) => l.received)).toEqual([20]);
  expect(await seed.orderStatus(order)).toBe("COMPLETED");
});
