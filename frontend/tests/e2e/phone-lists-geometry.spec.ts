import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * Phone lists measured at a real viewport.
 *
 * Unit tests cannot pin this: JSDOM has no layout, so a class-name assertion
 * passes on a bar whose last action starts beyond the screen edge. At 390 px
 * every action of the selection bar, and the archive's way back, must lie
 * inside the viewport without a sideways swipe; the quick actions on a
 * product card keep their 44 px boxes with nothing laid over their centres.
 */
const WIDTH = 390;

test.describe("Phone lists — nothing sits beyond the screen edge", () => {
  let api: ApiHelper;
  let token: string;
  const labelIds: string[] = [];
  let labelCodes: string[] = [];
  let archivedId: string;
  let longArchivedId: string;
  let storageId: string;
  let runTag: string;
  let archivedName: string;
  // One unbroken name sets the table's minimum width, whatever the other rows
  // hold; it comes with a reason badge, which the plain row lacks.
  let longArchivedName: string;

  test.beforeAll(async ({ playwright, baseURL }, testInfo) => {
    // Named per seed, not per file: with parallel tests a worker runs this
    // hook again for each test it is handed, and archived rows stay, so one
    // tag across two seeds found the plain row twice.
    runTag = `PhoneArchive${Math.random().toString(36).slice(2, 9)}`;
    archivedName = `${runTag} plain`;
    longArchivedName = `${runTag}IndustrialControllerReplacementModule`;
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;

    const labels = await api.generateLabels(token, 3, "PHN");
    labelIds.push(...labels.map((l) => l.id));
    labelCodes = labels.map((l) => l.short_code);

    storageId = (
      await api.createStorage(token, { name: `Z_Test Phone ${Date.now()}-w${testInfo.workerIndex}` })
    ).id;
    archivedId = (
      await api.createItem(token, {
        name: archivedName,
        quantity: 1,
        location_id: storageId,
      })
    ).id;
    await api.deleteItem(token, archivedId);
    longArchivedId = (
      await api.createItem(token, {
        name: longArchivedName,
        quantity: 1,
        location_id: storageId,
      })
    ).id;
    await api.deleteItem(token, longArchivedId, "TEST_DATA");
  });

  test.afterAll(async () => {
    for (const id of labelIds) await api.deleteLabel(token, id).catch(() => {});
    if (storageId) await api.deleteStorage(token, storageId).catch(() => {});
  });

  test.beforeEach(async ({ page, authenticatedPage }) => {
    await page.setViewportSize({ width: WIDTH, height: 844 });
  });

  test("the labels pool's selection bar shows every action on screen", async ({
    page,
  }) => {
    await page.goto("/inventory/labels");
    await page
      .getByRole("checkbox", { name: `Select label ${labelCodes[0]}` })
      .check({ timeout: 15000 });

    const bar = page.getByRole("toolbar");
    await expect(bar).toBeVisible();
    const buttons = bar.getByRole("button");
    const count = await buttons.count();
    // Clear, Delete Selected and Print Preview — the printer button joins
    // them where a printer is set up.
    expect(count).toBeGreaterThanOrEqual(3);
    for (let i = 0; i < count; i++) {
      const box = (await buttons.nth(i).boundingBox())!;
      expect(box.x, `action ${i} starts on screen`).toBeGreaterThanOrEqual(0);
      expect(
        box.x + box.width,
        `action ${i} ends on screen`,
      ).toBeLessThanOrEqual(WIDTH);
    }
    await expect(bar.getByRole("button", { name: /preview/i })).toBeInViewport({
      ratio: 1,
    });
  });

  test("the archive's Restore is reachable without a sideways scroll", async ({
    page,
  }) => {
    await page.goto("/inventory/items/archived");
    await page
      .getByPlaceholder(/search/i)
      .first()
      .fill(runTag);

    // Both rows on the page: one table sizes every row, so the long name must
    // not push the plain row's action out either.
    for (const name of [archivedName, longArchivedName]) {
      const row = page.getByRole("row", { name: new RegExp(name) });
      const restore = row.getByRole("button", { name: /restore/i });
      await expect(restore).toBeVisible({ timeout: 15000 });
      const box = (await restore.boundingBox())!;
      expect(box.x + box.width).toBeLessThanOrEqual(WIDTH);
    }
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("the product cards' quick actions keep 44 px boxes that nothing overlaps", async ({
    page,
  }) => {
    const names = [1, 2, 3].map((n) => `${runTag} card ${n}`);
    const ids: string[] = [];
    for (const name of names) {
      ids.push(
        (
          await api.createItem(token, {
            name,
            quantity: 5,
            location_id: storageId,
          })
        ).id,
      );
    }
    try {
      await page.goto("/inventory/items");
      await page
        .getByPlaceholder(/search/i)
        .first()
        .fill(runTag);
      const consume = page.getByRole("button", { name: "Remove 1 unit" });
      await expect(consume).toHaveCount(names.length, { timeout: 15000 });

      // Both quick actions of every adjacent card: the boxes, their pairwise
      // overlap, and what the browser finds at each centre. Each button is
      // scrolled into view first -- the last card sits under the phone's
      // bottom bar -- and its box is kept in page coordinates.
      const buttons = page
        .getByRole("button", {
          name: /^(Remove 1 unit|Product actions(: .+)?)$/,
        })
        .filter({ visible: true });
      await expect(buttons).toHaveCount(names.length * 2);
      const targets: {
        label: string | null;
        x: number;
        y: number;
        w: number;
        h: number;
        hitsItself: boolean;
      }[] = [];
      for (const button of await buttons.all()) {
        targets.push(
          await button.evaluate((b) => {
            // "If needed" leaves a button that only peeks out from under the
            // bottom bar where it is; the middle of the screen is clear.
            b.scrollIntoView({ block: "center" });
            const r = b.getBoundingClientRect();
            const hit = document.elementFromPoint(
              r.x + r.width / 2,
              r.y + r.height / 2,
            );
            return {
              label: b.getAttribute("aria-label"),
              x: r.x + window.scrollX,
              y: r.y + window.scrollY,
              w: r.width,
              h: r.height,
              hitsItself: !!hit && b.contains(hit),
            };
          }),
        );
      }
      expect(targets).toHaveLength(names.length * 2);
      for (const target of targets) {
        expect(target.w, `${target.label} width`).toBeGreaterThanOrEqual(44);
        expect(target.h, `${target.label} height`).toBeGreaterThanOrEqual(44);
        expect(target.hitsItself, `${target.label} centre`).toBe(true);
      }
      for (let i = 0; i < targets.length; i++) {
        for (let j = i + 1; j < targets.length; j++) {
          const a = targets[i];
          const b = targets[j];
          const overlaps =
            a.x < b.x + b.w - 0.5 &&
            b.x < a.x + a.w - 0.5 &&
            a.y < b.y + b.h - 0.5 &&
            b.y < a.y + a.h - 0.5;
          expect(overlaps, `targets ${i} and ${j} overlap`).toBe(false);
        }
      }
    } finally {
      for (const id of ids) await api.deleteItem(token, id).catch(() => {});
    }
  });
});
