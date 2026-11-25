import { test, expect } from "./fixtures/auth";
import { startSeed } from "./helpers/receive-seed";
import {
  arrivedField,
  chooseLocation,
  choosePartner,
} from "./helpers/receive-screen";

/**
 * A receipt in one step asks whether the shelf a line was put on is now the
 * product's home.
 *
 * The delivery goes to one shelf, but the worker names another for the line.
 * Once the receipt is posted a sheet asks about it; saying yes writes the
 * product's own putaway rule, read back through the API.
 */
test.use({ viewport: { width: 1280, height: 800 } });

test("a line put on its own shelf asks whether that shelf is the product's home", async ({
  page,
  playwright,
  baseURL,
  authenticatedPage: _auth,
}, testInfo) => {
  const seed = await startSeed({ playwright }, baseURL, testInfo);
  const delivery = await seed.shelf("Delivery");
  const home = await seed.shelf("Home");
  const supplier = await seed.partner("Supplier", "SUPPLIER");
  const rice = await seed.product("Rice");
  await seed.order(supplier, [{ product: rice, quantity: 5 }]);

  await page.goto("/warehouse/receive");
  await choosePartner(page, supplier.name);
  await chooseLocation(page, delivery.name);
  await expect(arrivedField(page, rice.name)).toHaveValue("5");
  await page.getByRole("combobox", { name: "Line location" }).click();
  await page.getByPlaceholder("Search locations").fill(home.name);
  await page.getByRole("button", { name: home.name }).click();
  await page.getByRole("button", { name: "Receive into stock" }).click();

  const sheet = page.getByRole("dialog", { name: "Home location" });
  await expect(sheet).toBeVisible({ timeout: 15000 });
  await expect(sheet).toContainText(rice.name);
  await expect(sheet).toContainText(home.name);
  await sheet
    .getByRole("button", { name: `Yes, make it the home: ${rice.name}` })
    .click();
  await expect(sheet).toBeHidden();

  const rules = await seed.request.get("/api/v1/warehouse/putaway-rules", {
    headers: { Authorization: `Bearer ${seed.token}` },
  });
  const { items } = (await rules.json()) as {
    items: Array<{
      product_template_id: string | null;
      target_location_id?: string | null;
    }>;
  };
  const rule = items.find((row) => row.product_template_id === rice.id);
  expect(rule?.target_location_id).toBe(home.id);
});
