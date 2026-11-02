import AxeBuilder from "@axe-core/playwright";
import type { APIRequestContext } from "@playwright/test";

import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * The announcement banner, end to end: publish one announcement of every type
 * through the API, check the banner a signed-in screen draws from them, delete
 * them again.
 *
 * An announcement is installation-wide — it shows above every screen of every
 * worker — so this spec runs in the `announcements` project, after the
 * parallel ones (see playwright.config.ts). The rendering alone, with the rows
 * served by a route, is covered in the parallel run by
 * announcement-banner-responsive.spec.ts.
 */
const TYPES = ["info", "warning", "critical", "downtime"] as const;
const FLOOR = 24;
const PREFIX = "E2E-banner";

test.describe("Announcement banner — published through the API", () => {
  // One worker, so the rows are published once; unlike `serial`, a failed
  // check does not skip the other.
  test.describe.configure({ mode: "default" });

  let request: APIRequestContext;
  let headers: Record<string, string>;
  const created: string[] = [];

  async function removeLeftovers() {
    const all = await request.get("/api/v1/announcements?limit=200", {
      headers,
    });
    expect(all.ok()).toBe(true);
    const { items } = (await all.json()) as {
      items: { id: string; title: string }[];
    };
    for (const a of items) {
      if (a.title.startsWith(PREFIX)) {
        await request.delete(`/api/v1/announcements/${a.id}`, { headers });
      }
    }
  }

  test.beforeAll(async ({ playwright, baseURL }) => {
    request = await playwright.request.newContext({ baseURL });
    const { access_token } = await new ApiHelper(request).login(
      ADMIN_EMAIL,
      ADMIN_PASSWORD,
    );
    headers = { Authorization: `Bearer ${access_token}` };
    // A run killed before its afterAll leaves its rows behind.
    await removeLeftovers();

    for (const type of TYPES) {
      const resp = await request.post("/api/v1/announcements", {
        headers,
        data: {
          title: `${PREFIX} ${type}`,
          content: "Scheduled maintenance tonight",
          type,
        },
      });
      expect(resp.status()).toBe(201);
      created.push(((await resp.json()) as { id: string }).id);
    }
  });

  // Runs after a failed test too: a row left here would sit above every
  // screen of the next run.
  test.afterAll(async () => {
    for (const id of created) {
      const resp = await request.delete(`/api/v1/announcements/${id}`, {
        headers,
      });
      expect([204, 404]).toContain(resp.status());
    }
    await request.dispose();
  });

  test("has no serious or critical axe finding for any type", async ({
    page,
    authenticatedPage,
  }) => {
    void authenticatedPage;
    // Wide enough for the type label, which is hidden below `sm`.
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/settings");
    const banner = page.getByRole("region", { name: "Announcements" });
    for (const type of TYPES) {
      await expect(banner.getByText(`${PREFIX} ${type}`)).toBeVisible({
        timeout: 15000,
      });
    }

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
    authenticatedPage,
  }) => {
    void authenticatedPage;
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
  });
});
