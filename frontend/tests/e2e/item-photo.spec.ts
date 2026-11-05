import { deflateSync } from "node:zlib";
import { test, expect } from "./fixtures/auth";
import type { Locator, Page, Request } from "@playwright/test";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * A photo picked in a product's edit sheet: it waits for Save, it is stored
 * after the update (which never carries the picture the sheet opened with),
 * and a replacement is a new address the screen shows at once.
 */
test.describe("Product edit — the picked photo", () => {
  let api: ApiHelper;
  let token: string;
  let storageId: string;
  let categoryId: string;
  let itemId: string;
  const suffix = Math.random().toString(36).substring(2, 9);
  const itemName = `Photo Product ${suffix}`;

  // A solid 8 x 8 PNG of one colour, written byte by byte: two colours give two different files and so two addresses.
  const png = (r: number, g: number, b: number) => {
    const crc = (buf: Buffer) => {
      let c = ~0;
      for (const byte of buf) {
        c ^= byte;
        for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xedb88320 & -(c & 1));
      }
      return ~c >>> 0;
    };
    const chunk = (type: string, data: Buffer) => {
      const body = Buffer.concat([Buffer.from(type), data]);
      const out = Buffer.alloc(12 + data.length);
      out.writeUInt32BE(data.length, 0);
      body.copy(out, 4);
      out.writeUInt32BE(crc(body), 8 + data.length);
      return out;
    };
    const header = Buffer.alloc(13);
    header.writeUInt32BE(8, 0);
    header.writeUInt32BE(8, 4);
    header[8] = 8; // bit depth
    header[9] = 2; // RGB
    const row = Buffer.concat([
      Buffer.from([0]),
      Buffer.from(Array(8).fill([r, g, b]).flat()),
    ]);
    return Buffer.concat([
      Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
      chunk("IHDR", header),
      chunk("IDAT", deflateSync(Buffer.concat(Array(8).fill(row)))),
      chunk("IEND", Buffer.alloc(0)),
    ]);
  };

  test.beforeAll(async ({ playwright, baseURL }) => {
    api = new ApiHelper(await playwright.request.newContext({ baseURL }));
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
    storageId = (
      await api.createStorage(token, {
        name: `Z_Photo Storage ${suffix}`,
        location_type_id: await api.ensureExpiryStorageType(token),
      })
    ).id;
    categoryId = (
      await api.createCategory(token, { name: `Z_Photo Category ${suffix}` })
    ).id;
    itemId = (
      await api.createItem(token, {
        name: itemName,
        quantity: 3,
        location_id: storageId,
        category_id: categoryId,
      })
    ).id;
  });

  test.afterAll(async () => {
    await api.deleteItem(token, itemId).catch(() => {});
    await api.deleteStorage(token, storageId).catch(() => {});
    await api.deleteCategory(token, categoryId).catch(() => {});
  });

  async function openSheet(page: Page): Promise<Locator> {
    await page.goto("/inventory/items");
    await page.getByTestId("item-name").filter({ hasText: itemName }).click();
    const dialog = page.locator('[role="dialog"]').filter({
      has: page.getByRole("heading", { name: "Edit product" }),
    });
    await expect(dialog).toBeVisible({ timeout: 10000 });
    return dialog;
  }

  const pick = (dialog: Locator, file: Buffer) =>
    dialog
      .locator('input[type="file"][accept="image/*"]')
      .setInputFiles({ name: "p.png", mimeType: "image/png", buffer: file });

  const save = (dialog: Locator) =>
    dialog.getByRole("button", { name: /^(save|zapisz)\b/i }).first();

  test("a picked photo is stored on Save, after an update that does not carry the old picture, and a replacement is a new address", async ({
    page,
    authenticatedPage,
  }) => {
    const sent: string[] = [];
    page.on("request", (request: Request) => {
      const { pathname } = new URL(request.url());
      if (!pathname.startsWith(`/api/v1/items/${itemId}`)) return;
      if (request.method() === "PUT") {
        sent.push(
          `PUT ${request.postData()?.includes("image_url") ? "with" : "without"} image_url`,
        );
      }
      if (request.method() === "POST" && pathname.endsWith("/image")) {
        sent.push("POST image");
      }
    });

    // First photo: picking sends nothing; Save sends the update, then the photo.
    let dialog = await openSheet(page);
    await pick(dialog, png(255, 0, 0));
    expect(sent).toEqual([]);
    await save(dialog).click();
    await expect(dialog).toBeHidden({ timeout: 15000 });
    expect(sent).toEqual(["PUT without image_url", "POST image"]);
    const first = String((await api.getItem(token, itemId)).image_url);
    expect(first).toContain("/cover.");

    // Replacing it: a different address, and the sheet shows the new picture.
    dialog = await openSheet(page);
    await pick(dialog, png(0, 0, 255));
    await save(dialog).click();
    await expect(dialog).toBeHidden({ timeout: 15000 });
    const second = String((await api.getItem(token, itemId)).image_url);
    expect(second).not.toBe(first);

    dialog = await openSheet(page);
    await expect(dialog.locator(`img[src="${second}"]`)).toBeVisible();
    // The previous file stays: a copy of the product may still name it.
    expect((await page.request.get(first)).status()).toBe(200);
  });

  test("Close drops a picked photo: nothing is uploaded", async ({
    page,
    authenticatedPage,
  }) => {
    const before = String((await api.getItem(token, itemId)).image_url);
    let posted = false;
    page.on("request", (request: Request) => {
      if (request.method() === "POST" && request.url().endsWith("/image"))
        posted = true;
    });
    const dialog = await openSheet(page);
    await pick(dialog, png(0, 255, 0));

    await page.keyboard.press("Escape");
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: /discard/i })
      .click();

    await expect(dialog).toBeHidden();
    expect(posted).toBe(false);
    expect(String((await api.getItem(token, itemId)).image_url)).toBe(before);
  });
});
