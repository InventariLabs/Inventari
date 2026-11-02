import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";

import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * Automated accessibility scan of the screens a user meets first.
 *
 * Runs axe-core (WCAG 2.0/2.1 A and AA rules) on each screen and fails on any
 * serious or critical violation the baseline does not already cover for that
 * screen. The baseline (`a11y-baseline.json`, next to this spec) freezes, per
 * rule, the kinds of element that were flagged when the scan was switched on,
 * so the suite is green on the code that exists and red on a screen that gets
 * worse: a new rule fails, and so does a new kind of element under a rule the
 * screen already breaks. It is written by the suite, never by hand:
 *
 *   A11Y_WRITE_BASELINE=1 npx playwright test a11y-axe --project=chromium --workers=1
 *
 * A kind of element is `signature()`: the tag with the attributes the markup
 * decides (class, role, type, data-testid). Neither axe's selector nor a node
 * count would do: the selector carries `:nth-child` positions, generated ids
 * and CSS classes picked by what else is on the page, and a count grows with
 * the data of the stack (one flagged button per item row, one tile per
 * enabled module), so the gate would flap on whatever the other specs created.
 * The price: a new element that is the very same kind as a frozen one (the
 * same component, copied) is not told apart from it.
 *
 * A signature in the baseline that no longer fires is reported in the run's
 * annotations ("paid") but does not fail it. Lower the paid entries with the
 * flag above.
 *
 * Every scan attaches its full report (all impacts, with the offending nodes)
 * to the test, so the HTML report is the list of what to fix.
 */

const BASELINE_PATH = new URL("./a11y-baseline.json", import.meta.url);
const WRITE_BASELINE = process.env.A11Y_WRITE_BASELINE === "1";
const BLOCKING = new Set(["serious", "critical"]);

type Baseline = { screens: Record<string, Record<string, string[]>> };

const readBaseline = (): Baseline =>
  JSON.parse(readFileSync(BASELINE_PATH, "utf8"));
const baseline = readBaseline();

/** Record what a screen shows now. One worker at a time: see the header. */
function writeScreen(screen: string, found: Record<string, string[]>) {
  const { screens } = readBaseline();
  if (Object.keys(found).length > 0) screens[screen] = found;
  else delete screens[screen];
  const sorted = Object.fromEntries(
    Object.entries(screens).sort(([a], [b]) => a.localeCompare(b)),
  );
  writeFileSync(
    BASELINE_PATH,
    `${JSON.stringify({ screens: sorted }, null, 2)}\n`,
  );
}

/** The kind of element a node is; see the header for why not its selector. */
function signature(html: string): string {
  const [, tag = "", attrs = ""] = html.match(/^<([\w-]+)([^>]*)>/) ?? [];
  const kept = ["class", "role", "type", "data-testid"].flatMap((name) => {
    const value = new RegExp(`\\s${name}="([^"]*)"`).exec(attrs)?.[1];
    return value === undefined ? [] : [`${name}=${value}`];
  });
  return [tag, ...kept].join(" ");
}

async function scan(page: Page, screen: string) {
  // A screen that fades in (the sign-in form takes 700 ms) is measured with
  // its text still half transparent when the machine is slow, and axe then
  // reports the contrast of a frame nobody reads. Wait for the animations
  // that end; a spinner's never does.
  await page.evaluate(() =>
    Promise.all(
      document
        .getAnimations()
        .filter((a) => a.effect?.getComputedTiming().endTime !== Infinity)
        .map((a) => a.finished.catch(() => undefined)),
    ),
  );
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();

  const blocking = results.violations.filter((v) =>
    BLOCKING.has(v.impact ?? ""),
  );
  const found = Object.fromEntries(
    blocking
      .map(
        (v) =>
          [
            v.id,
            [...new Set(v.nodes.map((n) => signature(n.html)))].sort(),
          ] as const,
      )
      .sort(([a], [b]) => a.localeCompare(b)),
  );

  await test.info().attach(`axe-${screen}.json`, {
    contentType: "application/json",
    body: JSON.stringify(
      results.violations.map((v) => ({
        id: v.id,
        impact: v.impact,
        help: v.help,
        helpUrl: v.helpUrl,
        nodes: v.nodes.map((n) => ({
          target: n.target,
          html: n.html,
          summary: n.failureSummary,
        })),
      })),
      null,
      2,
    ),
  });

  test.info().annotations.push({ type: "url", description: page.url() });

  const frozen = baseline.screens[screen] ?? {};
  for (const [id, signatures] of Object.entries(frozen)) {
    const gone = signatures.filter((sig) => !found[id]?.includes(sig));
    if (gone.length > 0) {
      test.info().annotations.push({
        type: "paid",
        description: `${screen}: ${id} no longer flags ${gone.join(" | ")}`,
      });
    }
  }
  if (WRITE_BASELINE) {
    writeScreen(screen, found);
    return;
  }

  const fresh = Object.entries(found).flatMap(([id, signatures]) =>
    signatures
      .filter((sig) => !frozen[id]?.includes(sig))
      .map((sig) => `${id}: ${sig}`),
  );
  expect(
    fresh,
    `${screen}: serious or critical accessibility violations beyond the baseline`,
  ).toEqual([]);
}

async function settle(page: Page) {
  await page
    .waitForLoadState("networkidle", { timeout: 15000 })
    .catch(() => {});
  await expect(page.getByRole("heading").first()).toBeVisible({
    timeout: 15000,
  });
}

test.describe("Accessibility — axe scan of the first screens", () => {
  test("login", async ({ page }) => {
    await page.goto("/login");
    await settle(page);
    await scan(page, "login");
  });

  test.describe("signed in", () => {
    // The `authenticatedPage` fixture signs the page in; every test asks for it.

    // The tray draws an unread badge only while something is unread, so a
    // scan of a header without one is green and the same scan after other
    // specs have filled the inbox is not. Serve a fixed inbox of unread
    // notifications to every signed-in screen: the badge is scanned on
    // purpose, in the same state whatever ran before. Two digits, because
    // axe sets a one-character badge aside as "too short to be text" and
    // never measures it.
    const UNREAD = 12;
    test.beforeEach(async ({ page }) => {
      await page.route(/\/api\/v1\/notifications(\?.*)?$/, async (route) => {
        if (route.request().method() !== "GET") return route.fallback();
        const items = Array.from({ length: UNREAD }, (_, i) => ({
          id: `00000000-0000-4000-8000-${String(i + 1).padStart(12, "0")}`,
          title: "Low stock alert",
          message: "An item is running low",
          is_read: false,
          created_at: new Date().toISOString(),
        }));
        await route.fulfill({
          json: {
            items,
            total: items.length,
            limit: 200,
            offset: 0,
            has_more: false,
          },
        });
      });
    });

    test("onboarding", async ({ page, authenticatedPage }) => {
      // The seeded organization finished onboarding, so the route would send
      // the page away. Tell the app it has not, and leave the rest of the
      // organization (and the profile list the wizard shows) real.
      await page.route("**/api/v1/organizations/my", async (route) => {
        const response = await route.fetch();
        await route.fulfill({
          response,
          json: { ...(await response.json()), onboarding_completed: false },
        });
      });
      await page.goto("/onboarding");
      await settle(page);
      expect(new URL(page.url()).pathname).toBe("/onboarding");
      await scan(page, "onboarding");
    });

    test("dashboard", async ({ page, authenticatedPage }) => {
      await page.goto("/launcher");
      await settle(page);
      // The badge is what the scan is here to measure.
      await expect(
        page.getByRole("button", { name: new RegExp(`${UNREAD} unread`, "i") }),
      ).toBeVisible();
      await scan(page, "dashboard");
    });

    test("item list", async ({ page, authenticatedPage }) => {
      await page.goto("/inventory/items");
      await settle(page);
      await scan(page, "item-list");
    });

    test("item form", async ({ page, authenticatedPage }) => {
      await page.goto("/inventory/items/add");
      await settle(page);
      await scan(page, "item-form");
    });

    test("storages", async ({ page, authenticatedPage }) => {
      await page.goto("/inventory/locations");
      await settle(page);
      await scan(page, "storages");
    });

    test("document form", async ({ page, authenticatedPage }) => {
      await page.goto("/warehouse");
      await settle(page);
      await page.getByRole("button", { name: /new document/i }).click();
      await page
        .getByRole("menuitem", { name: /receipt/i })
        .first()
        .click();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible({ timeout: 15000 });
      // Scanning mid-animation reads colours half way between two states.
      await dialog.evaluate((el) =>
        Promise.all(el.getAnimations({ subtree: true }).map((a) => a.finished)),
      );
      await scan(page, "document-form");
    });

    test("settings", async ({ page, authenticatedPage, request }) => {
      // The screen draws one more row, on a raised surface, once a person
      // has asked for access: seed one so the scan reads that row too.
      const api = new ApiHelper(request);
      const { access_token: token } = await api.login(
        ADMIN_EMAIL,
        ADMIN_PASSWORD,
      );
      const headers = { Authorization: `Bearer ${token}` };
      const email = `axe-request-${randomUUID()}@example.com`;
      const created = await request.post("/api/v1/auth/registration-request", {
        data: { email, full_name: "Axe Requester" },
      });
      expect(created.ok()).toBe(true);
      const listed = await request.get("/api/v1/auth/registration-requests", {
        headers,
      });
      const { items } = await listed.json();
      const seeded = items.find((r: { email: string }) => r.email === email);
      expect(seeded, "the seeded access request is listed").toBeTruthy();

      try {
        await page.goto("/settings");
        await settle(page);
        await expect(page.getByText(email)).toBeVisible({ timeout: 15000 });
        await scan(page, "settings");
      } finally {
        await request.post(
          `/api/v1/auth/registration-requests/${seeded.id}/reject`,
          { headers },
        );
      }
    });
  });
});
