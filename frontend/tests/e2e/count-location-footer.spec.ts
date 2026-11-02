import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * The sticky "start the count" card must not sit on the place it was meant to
 * count. Measured in a short window: JSDOM has no layout, and the overlap only
 * exists once the page is taller than the screen and the card is pinned to its
 * bottom edge. With the search narrowed to one place, a click on the middle of
 * that place's row landed on the card and left the start button disabled.
 */
test.describe("Count a location — the pinned footer leaves the list clickable", () => {
  let api: ApiHelper;
  let token: string;
  let locationId: string;
  const name = `CountFooter${Math.random().toString(36).slice(2, 9)}`;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
    locationId = (await api.createStorage(token, { name })).id;
  });

  test.afterAll(async () => {
    if (locationId) await api.deleteStorage(token, locationId).catch(() => {});
  });

  test("the middle of the only row reaches the row, not the card", async ({
    page,
    authenticatedPage,
  }) => {
    void authenticatedPage;
    await page.setViewportSize({ width: 1280, height: 577 });
    await page.goto("/inventory/stock-takes/count");
    await page.getByRole("textbox", { name: "Find a location" }).fill(name);

    // The list answers the typed text after a debounce: wait until it holds
    // that one place, not the rows of the previous query.
    const row = page.locator("ul button");
    await expect(row).toHaveCount(1, { timeout: 15000 });
    await expect(row).toContainText(name);
    // The footer is the only thing pinned to the window; a long page keeps it
    // over the fold, so no scrolling here -- that is what a first click does.
    await page.evaluate(() => window.scrollTo(0, 0));

    const hitsRow = await row.evaluate((el) => {
      const r = el.getBoundingClientRect();
      const hit = document.elementFromPoint(
        r.x + r.width / 2,
        r.y + r.height / 2,
      );
      return !!hit && el.contains(hit);
    });
    expect(hitsRow).toBe(true);

    await row.click();
    await expect(
      page.getByRole("button", { name: new RegExp(`Count .*${name}`) }),
    ).toBeEnabled();
  });
});
