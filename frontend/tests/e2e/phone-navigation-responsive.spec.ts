import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * Moving between screens on a phone: a new screen opens at its top, and Back
 * goes to the screen the person came from.
 *
 * Unit tests cannot see either — jsdom has no scrolling and no viewport. The
 * defect was a product list scrolled down, a row menu, "Product details": the
 * page opened at the scroll position of the list, with the name and quantity
 * above the screen, and the header Back arrow then left the module for the
 * launcher instead of returning to the list.
 */

test.describe("Phone — a new screen opens at its top and Back returns", () => {
  let api: ApiHelper;
  let token: string;
  const createdIds: string[] = [];
  // Carried by the names, so the search narrows to this run's products and
  // nothing the organization holds already.
  let tag = "phone-nav";

  // One worker owns the products below; a second would seed its own copy and
  // the list would hold twice as many rows as the test counts.
  test.describe.configure({ mode: "serial" });

  test.beforeAll(async ({ playwright, baseURL }, testInfo) => {
    // The projects run side by side: each seeds and searches its own set.
    tag = `phone-nav-${testInfo.project.name}`;
    createdIds.length = 0;
    api = new ApiHelper(await playwright.request.newContext({ baseURL }));
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
    const storages = await api.listStorages(token);
    const storageId = process.env.E2E_STORAGE_ID || storages[0]?.id || "";
    // Enough rows that the list is several screens tall on a 360x800 phone.
    for (let n = 10; n < 40; n++) {
      const item = await api.createItem(token, {
        name: `Phone nav ${tag} ${n}`,
        quantity: 3,
        location_id: storageId,
      });
      createdIds.push(item.id);
    }
  });

  /** A confirmed order with one open line, for the receipt to wait for. */
  async function seedConfirmedOrder() {
    const supplier = await api.createPartner(token, {
      name: `Phone nav supplier ${tag} ${Date.now()}`,
      type: "SUPPLIER",
    });
    const template = await api.createProductTemplate(token, {
      name: `Phone nav goods ${tag} ${Date.now()}`,
    });
    const order = await api.createPurchaseOrder(token, {
      partner_id: supplier.id,
      status: "DRAFT",
      lines: [
        {
          product_template_id: template.id,
          quantity_ordered: 4,
          unit_price: "2.00",
        },
      ],
    });
    await api.confirmPurchaseOrder(token, order.id);
    return { ...order, partnerId: supplier.id };
  }

  test.afterAll(async () => {
    for (const id of createdIds) {
      await api.deleteItem(token, id).catch(() => {});
    }
  });

  test("product details from a scrolled list opens at the top; Back returns to the list", async ({
    page,
    authenticatedPage,
  }) => {
    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto(`/inventory/items?search=${tag}`);

    // Scroll to the last card and open its row menu.
    const menus = page.getByRole("button", { name: /^Product actions: / });
    // The search narrows the list after the first paint: wait for it, or the
    // last card read below belongs to a list that is about to be replaced.
    await expect(menus).toHaveCount(createdIds.length, { timeout: 15000 });
    const last = menus.last();
    // The page scrolls as a whole; a plain scroll to the bottom is what a
    // thumb does, and leaves the last card in reach.
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await expect(last).toBeInViewport();
    const leftAt = await page.evaluate(() => window.scrollY);
    expect(leftAt).toBeGreaterThan(500);
    const name = (await last.getAttribute("aria-label"))!.replace(
      "Product actions: ",
      "",
    );
    await last.click();
    await page.getByRole("button", { name: "Product details" }).click();

    // The product's own name is on the first screen, not above it.
    const heading = page.getByRole("heading", { name, level: 1 });
    await expect(heading).toBeVisible();
    await expect(heading).toBeInViewport();
    expect(await page.evaluate(() => window.scrollY)).toBe(0);

    // Back is the previous screen: the list, not the launcher.
    await page.getByRole("button", { name: "Back" }).click();
    await expect(page).toHaveURL(/\/inventory\/items\?search=phone-nav/);
    await expect(menus.first()).toBeVisible();

    // …and the list is where it was left, not clamped to the short page the
    // browser found while the list was still being fetched.
    await expect
      .poll(() => page.evaluate(() => window.scrollY), { timeout: 10000 })
      .toBeGreaterThanOrEqual(leftAt - 2);
  });

  test("a search typed into the list is still there after Back", async ({
    page,
    authenticatedPage,
  }) => {
    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto("/inventory/items");
    const search = page.getByPlaceholder(/search/i).first();
    const query = `Phone nav ${tag} 12`;
    await search.fill(query);
    const menus = page.getByRole("button", { name: /^Product actions: / });
    // Narrowed from the whole list down to the match.
    await expect
      .poll(() => menus.count(), { timeout: 15000 })
      .toBeLessThan(createdIds.length);
    await expect(page).toHaveURL(/search=/);

    await menus.first().click();
    await page.getByRole("button", { name: "Product details" }).click();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

    await page.getByRole("button", { name: "Back" }).click();
    await expect(search).toHaveValue(query);
    await expect
      .poll(() => menus.count(), { timeout: 15000 })
      .toBeLessThan(createdIds.length);
  });

  test("two filter chips stay on together, and still do after Back", async ({
    page,
    authenticatedPage,
  }) => {
    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto("/inventory/items");
    const lowStock = page.getByRole("button", { name: "Running low" });
    const usedUp = page.getByRole("button", { name: "Show used up" });
    await lowStock.click();
    await usedUp.click();
    // Each chip owns its place in the address; ticking the second must not
    // untick the first.
    await expect(lowStock).toHaveAttribute("aria-pressed", "true");
    await expect(usedUp).toHaveAttribute("aria-pressed", "true");
    // A chip is the reader's own tap: the place and category pickers stay
    // folded away instead of pushing the list down.
    await expect(page.locator("#items-domain-filters")).toHaveCount(0);
    // The pressed state is read from the screen's state at once; the address
    // is written a beat later. Reloading in between brings back no chips, so
    // wait for the address the reload will read.
    await expect
      .poll(() =>
        (new URL(page.url()).searchParams.get("filter") ?? "")
          .split(",")
          .sort()
          .join(","),
      )
      .toBe("low-stock,used-up");
    await page.reload();
    await expect(lowStock).toHaveAttribute("aria-pressed", "true");
    await expect(usedUp).toHaveAttribute("aria-pressed", "true");
  });

  test("Back from a product opened by a direct link climbs, then leaves the module", async ({
    page,
    authenticatedPage,
  }) => {
    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto(`/inventory/items/${createdIds[0]}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

    // A replaced entry gets a new key but no history: Back must not stall.
    await page.getByRole("button", { name: "Back" }).click();
    await expect(page).toHaveURL(/\/inventory\/items$/);
    // The address changes before the screen does; press Back only once the
    // list is on screen, as a person would.
    await expect(page.getByRole("heading", { name: "Products" })).toBeVisible();
    await page.getByRole("button", { name: "Back" }).click();
    await expect(page).toHaveURL(/\/inventory$/);
  });

  // Every screen the Warehouse start opens with a "back to the start" in its
  // router state: the four actions and the two related screens.
  const fromWarehouseStart = [
    { name: "Move", open: /^Move/, role: "button", url: /\/warehouse\/move$/ },
    {
      name: "Issue goods",
      open: /^Issue goods/,
      role: "button",
      url: /\/warehouse\/issue$/,
    },
    {
      name: "Count",
      open: /^Count/,
      role: "button",
      url: /\/inventory\/stock-takes\/count$/,
    },
    { name: "Stock", open: "Stock", role: "link", url: /\/inventory\/stock$/ },
    {
      name: "Stock takes",
      open: "Stock takes",
      role: "link",
      url: /\/inventory\/stock-takes$/,
    },
  ] as const;

  for (const entry of fromWarehouseStart) {
    test(`Back from ${entry.name}, opened on the Warehouse start, reaches the start and then the launcher`, async ({
      page,
      authenticatedPage,
    }) => {
      await page.setViewportSize({ width: 360, height: 800 });
      await page.goto("/launcher");
      // Not by name: the profile chip ("Equipment & Warehouse") is a link too,
      // and the tile's name carries its "to do today" badge.
      await page.locator('a[href="/warehouse/todo"]').first().click();
      await expect(page).toHaveURL(/\/warehouse\/todo$/);

      await page
        .getByRole(entry.role, { name: entry.open, exact: false })
        .first()
        .click();
      await expect(page).toHaveURL(entry.url);

      // The start is on screen again, and one more Back leaves for the
      // launcher. The shell used to push the start a second time, so the next
      // Back popped to the action and the two screens took turns for ever.
      await page.getByRole("button", { name: "Back" }).click();
      await expect(page).toHaveURL(/\/warehouse\/todo$/);
      await page.getByRole("button", { name: "Back" }).click();
      await expect(page).toHaveURL(/\/launcher$/);
    });
  }

  test("Back from a receipt opened on a purchase order returns to the order, the list, the launcher", async ({
    page,
    authenticatedPage,
  }) => {
    const seeded = await seedConfirmedOrder();
    try {
      await page.setViewportSize({ width: 360, height: 800 });
      await page.goto("/launcher");
      await page.locator('a[href="/purchase-orders"]').first().click();
      await expect(page).toHaveURL(/\/purchase-orders$/);
      await page.getByText(seeded.number).first().click();
      await expect(page).toHaveURL(/\/purchase-orders\/[0-9a-f-]+$/);

      await expect(
        page.getByRole("heading", { name: seeded.number }),
      ).toBeVisible();

      await page.getByRole("button", { name: "More actions" }).click();
      await page.getByRole("button", { name: "Receive delivery" }).click();
      await expect(page).toHaveURL(/\/warehouse\/receive\?order=/);

      // The order, not a second copy of it that sends the next Back to the
      // receipt again.
      await page.getByRole("button", { name: "Back" }).click();
      await expect(page).toHaveURL(/\/purchase-orders\/[0-9a-f-]+$/);
      await page.getByRole("button", { name: "Back" }).click();
      await expect(page).toHaveURL(/\/purchase-orders$/);
      await page.getByRole("button", { name: "Back" }).click();
      await expect(page).toHaveURL(/\/launcher$/);
    } finally {
      await api.cancelPurchaseOrder(token, seeded.id).catch(() => {});
      await api.deletePartner(token, seeded.partnerId).catch(() => {});
    }
  });
});
