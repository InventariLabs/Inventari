import AxeBuilder from "@axe-core/playwright";

import { test, expect } from "./fixtures/auth";

/**
 * The announcement banner, with one announcement of every type on screen.
 *
 * The banner sits above every signed-in screen, so a defect in it shows on all
 * of them at once — and only while an announcement is active, which none of the
 * other specs arrange. The announcements are served to this page alone through
 * a route, not created on the stack: an announcement in the database would
 * appear on every screen the parallel workers are driving. Publishing and
 * removing real ones is announcement-publish.spec.ts, which runs after them.
 *
 * The file name keeps the word "responsive": the `mobile` project selects its
 * specs by that pattern (see playwright.config.ts).
 */
const TYPES = ["info", "warning", "critical", "downtime"] as const;
const FLOOR = 24;

test.describe("Announcement banner", () => {
  test.beforeEach(async ({ page, authenticatedPage }) => {
    void authenticatedPage;
    const banners = TYPES.map((type, i) => ({
      id: `00000000-0000-4000-8000-00000000000${i}`,
      title: `Banner ${type}`,
      content: "Scheduled maintenance tonight",
      type,
      active_from: "2026-01-01T00:00:00Z",
      active_until: null,
      is_active: true,
      created_at: "2026-01-01T00:00:00Z",
      created_by: null,
    }));
    // Matched on the path: the reader asks a page at a time, so the address
    // carries `limit` and `offset`.
    await page.route(
      (url) => url.pathname === "/api/v1/announcements/active",
      (route) =>
        route.fulfill({
          json: {
            items: banners,
            total: banners.length,
            limit: 200,
            offset: 0,
            has_more: false,
          },
        }),
    );
  });

  test("has no serious or critical axe finding for any type", async ({
    page,
  }) => {
    // Wide enough for the type label, which is hidden below `sm`.
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/settings");
    const banner = page.getByRole("region", { name: "Announcements" });
    await expect(banner.getByText("Banner downtime")).toBeVisible({
      timeout: 15000,
    });

    const results = await new AxeBuilder({ page })
      .include('[role="region"][aria-label="Announcements"]')
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    const blocking = results.violations
      .filter((v) => v.impact === "serious" || v.impact === "critical")
      .flatMap((v) => v.nodes.map((n) => `${v.id}: ${n.html.slice(0, 120)}`));
    expect(blocking).toEqual([]);
  });

  test(`every dismiss button is at least ${FLOOR}x${FLOOR} at 390px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/settings");
    const dismiss = page
      .getByRole("region", { name: "Announcements" })
      .getByRole("button", { name: "Dismiss" });
    await expect(dismiss).toHaveCount(TYPES.length, { timeout: 15000 });

    for (const button of await dismiss.all()) {
      const box = await button.boundingBox();
      expect(box?.width ?? 0).toBeGreaterThanOrEqual(FLOOR);
      expect(box?.height ?? 0).toBeGreaterThanOrEqual(FLOOR);
    }

    await dismiss.first().click();
    await expect(dismiss).toHaveCount(TYPES.length - 1);
  });
});
