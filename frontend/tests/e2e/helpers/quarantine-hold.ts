import { expect, type Page } from "@playwright/test";
import { arrivedField, chooseLocation, choosePartner } from "./receive-screen";
import type { ReceivingSeed, SeededProduct, SeededShelf } from "./receive-seed";

/**
 * Goods held in quarantine without a batch: a delivery of twenty comes in
 * through the Receive screen with two of them damaged, so two stand on the
 * quarantine shelf under the receipt's reservation and eighteen are stock.
 * That reservation is what the Start screen's quarantine block lists.
 */
export interface HeldGoods {
  product: SeededProduct;
  shelf: SeededShelf;
  quarantine: SeededShelf;
  /** The receipt that placed the hold, as its number is printed. */
  receiptNumber: string;
}

export const DELIVERED = 20;
export const HELD = 2;

export async function receiveWithDamagedGoods(
  page: Page,
  seed: ReceivingSeed,
): Promise<HeldGoods> {
  const shelf = await seed.shelf("Shelf");
  const quarantine = await seed.shelf("Quarantine");
  const supplier = await seed.partner("Supplier", "SUPPLIER");
  const product = await seed.product("Held");
  await seed.order(supplier, [{ product, quantity: DELIVERED }]);
  const named = await seed.request.put("/api/v1/warehouse/profile", {
    headers: { Authorization: `Bearer ${seed.token}` },
    data: { quarantine_location_id: quarantine.id },
  });
  expect(named.ok()).toBe(true);

  await page.goto("/warehouse/receive");
  await choosePartner(page, supplier.name);
  await chooseLocation(page, shelf.name);
  await expect(arrivedField(page, product.name)).toHaveValue(String(DELIVERED));
  await page.getByRole("button", { name: "Damaged or on hold" }).click();
  await page
    .getByRole("textbox", { name: `Damaged or on hold: ${product.name}` })
    .fill(String(HELD));
  await page.getByRole("button", { name: "Receive into stock" }).click();
  await expect(
    page.getByRole("heading", { name: /^Received \d+ lines?$/ }),
  ).toBeVisible({ timeout: 15000 });

  const receipt = await seed.documentLinkedFrom(page);
  expect(await seed.onHand(product, shelf)).toBe(DELIVERED - HELD);
  expect(await seed.onHand(product, quarantine)).toBe(HELD);
  return {
    product,
    shelf,
    quarantine,
    receiptNumber: receipt.number as string,
  };
}
