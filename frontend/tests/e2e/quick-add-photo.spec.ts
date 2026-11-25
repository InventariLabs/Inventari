import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * Adding a product from a photo, driven the way an automated browser drives
 * it: the picture is handed to the file input the camera tab keeps in the
 * document, the reading comes back, and the product is saved.
 *
 * The model is the one stand-in here. Its answer is canned — a real reading
 * needs an AI connection and is not deterministic — but the request that
 * reaches it must carry the very file that was chosen.
 */
test.describe("Quick add — a product from a photo", () => {
  let api: ApiHelper;
  let token: string;
  let storageName: string;
  let storageId: string;
  const suffix = Math.random().toString(36).substring(2, 9);
  const productName = `Z_Photo Read ${suffix}`;

  test.beforeAll(async ({ playwright, baseURL }) => {
    api = new ApiHelper(await playwright.request.newContext({ baseURL }));
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
    storageName = `Z_Photo Shelf ${suffix}`;
    storageId = (
      await api.createStorage(token, {
        name: storageName,
        location_type: "SHELF",
      })
    ).id;
  });

  test.afterAll(async () => {
    for (const item of await api.listItems(token, `search=${suffix}`)) {
      await api.deleteItem(token, item.id).catch(() => {});
    }
    await api.deleteStorage(token, storageId).catch(() => {});
  });

  test("a photo handed to the picker is read and the product is saved", async ({
    page,
    authenticatedPage,
  }) => {
    // The registry says the image reading is bound, so the camera is open.
    await page.route("**/api/v1/ai-connections/purposes*", (route) =>
      route.fulfill({
        json: {
          items: [{ key: "vision.extract", bound_connection_id: "c", usable: true }],
          has_more: false,
        },
      }),
    );
    let uploaded = "";
    await page.route("**/api/v1/vision/extract", async (route) => {
      uploaded = route.request().postData() ?? "";
      await route.fulfill({
        json: {
          name: productName,
          weight: null,
          expiry_date: null,
          production_date: null,
          brand: null,
          category: null,
          barcode: null,
        },
      });
    });

    await page.goto("/inventory/items");
    await page.getByRole("button", { name: "Add product" }).click();
    await page.getByRole("tab", { name: "From photo" }).click();

    await page.getByTestId("vision-photo-input").setInputFiles({
      name: "label.png",
      mimeType: "image/png",
      buffer: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==",
        "base64",
      ),
    });
    await page.getByRole("button", { name: /^analyze/i }).click();

    // The reading lands in the form, and the request carried the photo.
    await expect(
      page.getByRole("textbox", { name: /product name/i }),
    ).toHaveValue(productName);
    expect(uploaded).toContain('name="images"');

    await page.getByRole("combobox", { name: /location/i }).click();
    await page
      .getByRole("dialog")
      .last()
      .getByRole("textbox", { name: /^Search/ })
      .fill(storageName);
    await page
      .getByRole("button", { name: new RegExp(`^${storageName}`) })
      .click();
    await page.getByRole("button", { name: "Add Product" }).click();

    await expect(page).toHaveURL(/\/inventory\/items$/);
    await expect
      .poll(async () => (await api.searchProducts(token, productName)).length)
      .toBeGreaterThan(0);
  });
});
