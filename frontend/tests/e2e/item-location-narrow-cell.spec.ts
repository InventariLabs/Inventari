import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * The product list's location cell measured at a real viewport.
 *
 * jsdom has no layout, so the unit test can only pin the classes that keep
 * the leaf of a path uncut. Here the path is longer than the cell on purpose:
 * the road to the leaf must be the part that gives, never the leaf itself,
 * because records of one product on different shelves differ only there.
 */
const LEAF = "Shelf A - Bottom Row Seven";

// The table shows from `lg` (1024 px); below it the list is a stack of cards.
for (const width of [1024, 1280]) {
  test(`${width}px: a long location path loses its road, not its leaf`, async ({
    page,
    request,
    authenticatedPage,
  }, testInfo) => {
    void authenticatedPage;
    const suffix = `${Date.now()}-w${testInfo.workerIndex}-${width}`;
    const api = new ApiHelper(request);
    const token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
    const ids: string[] = [];
    let itemId = "";
    try {
      const site = await api.createStorage(token, {
        name: `Distribution Centre North Building ${suffix}`,
      });
      ids.push(site.id);
      const zone = await api.createStorage(token, {
        name: "Ambient Dry Goods Overflow Zone",
        parent_id: site.id,
      });
      ids.push(zone.id);
      const shelf = await api.createStorage(token, {
        name: LEAF,
        parent_id: zone.id,
      });
      ids.push(shelf.id);
      const itemName = `Narrow cell product ${suffix}`;
      itemId = (
        await api.createItem(token, {
          name: itemName,
          quantity: 3,
          location_id: shelf.id,
        })
      ).id;

      await page.setViewportSize({ width, height: 900 });
      await page.goto("/inventory/items");
      const row = page.getByTestId("item-row").filter({ hasText: itemName });
      await expect(row).toBeVisible({ timeout: 15000 });

      const leaf = row.getByText(LEAF);
      const parents = row.getByTestId("item-location-parents");
      await expect(leaf).toBeVisible();

      // Not a vacuous cell: the road is wider than the room it was given.
      const road = await parents.evaluate((el) => ({
        scroll: el.scrollWidth,
        client: el.clientWidth,
      }));
      expect(road.scroll).toBeGreaterThan(road.client);

      // The leaf is laid out in full: no clipped text, and it stays inside
      // the link that carries it.
      const clip = await leaf.evaluate((el) => ({
        scroll: el.scrollWidth,
        client: el.clientWidth,
      }));
      expect(clip.scroll).toBeLessThanOrEqual(clip.client);
      const link = row.getByRole("link", { name: new RegExp(LEAF) });
      const linkBox = (await link.boundingBox())!;
      const leafBox = (await leaf.boundingBox())!;
      expect(leafBox.x).toBeGreaterThanOrEqual(linkBox.x - 1);
      expect(leafBox.x + leafBox.width).toBeLessThanOrEqual(
        linkBox.x + linkBox.width + 1,
      );
    } finally {
      if (itemId) await api.deleteItem(token, itemId);
      // A place that took stock keeps its movement history and refuses to go;
      // the names carry a per-run suffix, so a leftover collides with nothing.
      for (const id of ids.reverse())
        await api.deleteStorage(token, id).catch(() => {});
    }
  });
}
