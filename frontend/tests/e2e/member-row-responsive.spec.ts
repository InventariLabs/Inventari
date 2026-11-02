import { test, expect } from "./fixtures/auth";

/**
 * The member row measured at a real viewport.
 *
 * Unit tests cannot pin this: JSDOM has no layout, so a class-name assertion
 * passes on a row whose address is already clipped. At 390 px the identity
 * column must get the whole line (the role control drops under it) and a long
 * address must wrap rather than lose its ending.
 */

const LONG_A = "magazyn.operacje.kierownik@dzial.firma.example.com";
const LONG_B = "magazyn.operacje.kierownik@dzial.firma.example.org";

test.describe("Settings — member row responsive", () => {
  test.beforeEach(async ({ page, authenticatedPage }) => {
    await page.route("**/organizations/my/members*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        json: {
          items: [
            {
              id: "m-1",
              email: LONG_A,
              full_name: "Manager One",
              role: "user",
            },
            {
              id: "m-2",
              email: LONG_B,
              full_name: "Manager Two",
              role: "user",
            },
          ],
          total: 2,
          limit: 20,
          offset: 0,
        },
      });
    });
  });

  // 768 px is the band the side navigation used to squeeze: the row was
  // already horizontal (`md`) and the address clipped at 182 px of 307.
  for (const width of [390, 768]) {
    test(`${width}px: identity takes the line, address is not clipped, role control sits below`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/settings");

      const email = page.getByText(LONG_A, { exact: true });
      await expect(email).toBeVisible({ timeout: 15000 });

      // Not clipped: the text is fully laid out inside its box.
      const clip = await email.evaluate((el) => ({
        scroll: el.scrollWidth,
        client: el.clientWidth,
      }));
      expect(clip.scroll).toBeLessThanOrEqual(clip.client);

      // Two addresses that differ only in the last label stay distinguishable.
      await expect(page.getByText(LONG_B, { exact: true })).toBeVisible();

      const row = page.locator(".group", { has: email }).first();
      const rowBox = (await row.boundingBox())!;
      const identity = (await email.boundingBox())!;
      // The identity column spans (almost) the whole row, not a ~50 px sliver.
      expect(identity.width).toBeGreaterThan(rowBox.width * 0.6);

      // The role control, when the row carries one, is on its own line.
      const select = row.locator("select");
      if (await select.count()) {
        const sel = (await select.boundingBox())!;
        expect(sel.y).toBeGreaterThanOrEqual(identity.y + identity.height);
      }
    });
  }
});
