import { test, expect } from "./fixtures/auth";
import { startSeed } from "./helpers/receive-seed";
import {
  arrivedField,
  chooseLocation,
  choosePartner,
} from "./helpers/receive-screen";
import { isoDay, pickDay } from "./helpers/date-picker";

/**
 * A delivery of a product taken by earliest expiry cannot arrive undated.
 *
 * The server refuses the post and names the row; the sheet opens that row's
 * Lot and expiry, says which product needs a date, and keeps everything the
 * reader typed. Once the date is given the same press posts. Read back
 * through the API: nothing reached the shelf before the date, all of it after.
 */
test.use({ viewport: { width: 1280, height: 800 } });

test("an undated delivery of a product taken by expiry opens the row's date and names the product", async ({
  page,
  playwright,
  baseURL,
  authenticatedPage: _auth,
}, testInfo) => {
  const seed = await startSeed({ playwright }, baseURL, testInfo);
  const shelf = await seed.shelf("Shelf");
  const supplier = await seed.partner("Supplier", "SUPPLIER");
  const yoghurt = await seed.product("Yoghurt", true);
  await seed.order(supplier, [{ product: yoghurt, quantity: 6 }]);

  await page.goto("/warehouse/receive");
  await choosePartner(page, supplier.name);
  await chooseLocation(page, shelf.name);
  await expect(arrivedField(page, yoghurt.name)).toHaveValue("6");
  // Nothing about the row asks for a date until the server does.
  await expect(page.getByLabel("Expiry")).toHaveCount(0);

  await page.getByRole("button", { name: "Receive into stock" }).click();

  await expect(
    page.getByText(`Expiry date needed for: ${yoghurt.name}.`),
  ).toBeVisible({ timeout: 15000 });
  const expiry = page.getByRole("combobox", { name: "Expiry" });
  await expect(expiry).toBeVisible();
  await expect(page.getByText("Needed for this product")).toBeVisible();
  expect(await seed.onHand(yoghurt, shelf)).toBe(0);
  // What was typed stays: the count is still the delivery's.
  await expect(arrivedField(page, yoghurt.name)).toHaveValue("6");

  await pickDay(page, expiry, isoDay(10));
  await page.getByRole("button", { name: "Receive into stock" }).click();

  await expect(
    page.getByRole("heading", { name: /^Received \d+ lines?$/ }),
  ).toBeVisible({ timeout: 15000 });
  expect(await seed.onHand(yoghurt, shelf)).toBe(6);
  const document = await seed.documentLinkedFrom(page);
  expect(document.lines).toMatchObject([{ expiry_date: isoDay(10) }]);
});
