import type { Page } from "@playwright/test";
import { RELOAD_GUARD_KEY } from "../../src/lib/staleChunk";
import { test, expect } from "./fixtures/auth";

/**
 * The dev server hands the browser one request per module. When the host's
 * network changes mid-load (another stack's bridge coming up, a VPN toggling),
 * Chromium aborts whatever is in flight with `net::ERR_NETWORK_CHANGED`, and
 * the lazy route shows the error boundary instead of the page. A reload is the
 * only way out: the module map keeps a failed dependency as failed, so a second
 * `import()` of the same module fails the same way.
 *
 * The module it aborts is named for both servers: the dev server's one file
 * per component, and the hashed chunk a production build folds the same
 * component into. The build has no `ItemsContent.tsx`, so a pattern for the
 * dev server alone never fires there and the spec cannot tell a harness that
 * recovers from one that was never tested.
 *
 * This spec fakes that abort for one module of the items page and asserts the
 * harness recovers, so the other ~600 tests do not each carry a retry of their
 * own for a failure that has nothing to do with them.
 */
const ITEMS_PAGE_MODULE =
  /\/ItemsPage\/ItemsContent\.tsx|\/assets\/ItemsPage-[\w-]+\.js/;

test.describe("Transient module load failure", () => {
  test("a lazy module aborted once does not leave the error boundary on screen", async ({
    page,
    authenticatedPage,
  }) => {
    // The app reloads itself once after a failed chunk (lib/staleChunk.ts).
    // Mark that reload as spent, so the failure reaches the error boundary and
    // only the harness is left to recover from it.
    await page.addInitScript((key) => {
      sessionStorage.setItem(key, String(Date.now()));
    }, RELOAD_GUARD_KEY);

    let aborted = 0;
    let markAborted!: () => void;
    const abortFired = new Promise<void>((resolve) => (markAborted = resolve));
    await page.route(ITEMS_PAGE_MODULE, (route) => {
      if (aborted++ === 0) {
        markAborted();
        return route.abort("failed");
      }
      return route.continue();
    });

    await page.goto("/inventory/items");

    // Under load a heading from the shell can render before the lazy module is
    // ever requested, so the heading check alone can pass without the fake
    // failure having happened. Wait for the abort first.
    await Promise.race([
      abortFired,
      new Promise((_, reject) =>
        setTimeout(
          () => reject(new Error("the fake abort never fired")),
          15000,
        ),
      ),
    ]);

    // The error boundary has headings of its own ("Something went wrong",
    // "A new version is ready"), so a heading check passes on the failure
    // itself. The list's search box exists only once the aborted module loaded.
    await expect(page.getByTestId("list-search-input")).toBeVisible({
      timeout: 15000,
    });
    expect(aborted, "the fake abort never fired").toBeGreaterThan(0);
  });
});

/**
 * Navigation returns at the `load` event, seconds before the app has drawn
 * anything on a loaded host, and a recovery reload starts that over. Neither
 * belongs to the wait a spec writes after `goto`, nor to the test's clock
 * (fixtures/base.ts). The hold on the boot's first request makes a loaded host
 * of a quiet one: it is longer than the wait and than the test's whole budget.
 */
test.describe("Slow start of the app", () => {
  const BOOT_REQUEST = "**/api/v1/auth/refresh";
  const HOLD = 12_000;
  const holdBoot = (page: Page) =>
    page.route(BOOT_REQUEST, async (route) => {
      await new Promise((resolve) => setTimeout(resolve, HOLD));
      await route.continue().catch(() => {});
    });

  test("is charged neither to the wait after goto nor to the test", async ({
    page,
    authenticatedPage,
  }) => {
    test.setTimeout(HOLD);
    await holdBoot(page);

    await page.goto("/inventory/items");

    await expect(page.getByTestId("list-search-input")).toBeVisible({
      timeout: HOLD - 2000,
    });
  });

  test("a recovery reload inside the start is waited for too", async ({
    page,
    authenticatedPage,
  }) => {
    test.setTimeout(HOLD);
    // Spent, as above: the failure must reach the harness, not the app's own
    // reload.
    await page.addInitScript((key) => {
      sessionStorage.setItem(key, String(Date.now()));
    }, RELOAD_GUARD_KEY);
    await holdBoot(page);
    // The app's own chunk, which the boot imports before it draws anything:
    // its failure is the error boundary, which is not a started app's page.
    let aborted = 0;
    await page.route(/\/src\/App\.tsx|\/assets\/App-[\w-]+\.js/, (route) =>
      aborted++ === 0 ? route.abort("failed") : route.continue(),
    );

    await page.goto("/inventory/items");

    await expect(page.getByTestId("list-search-input")).toBeVisible({
      timeout: HOLD - 2000,
    });
    expect(aborted, "the fake abort never fired").toBeGreaterThan(1);
  });
});

/**
 * The race the recovery reload runs against: an error screen is on the page
 * and the reload that clears it has not begun. The harness only hears of the
 * failure after the screen is drawn, so whether it wins is down to the host's
 * load. The failed module schedules the reload itself, which leaves the screen
 * up for a fixed while and keeps the harness out of it: `goto` is only done
 * with the start if it was still waiting when the second request came.
 */
test.describe("An error screen during the start", () => {
  const FAILED_MODULE = `
    setTimeout(() => location.reload(), 2000);
    throw new Error("this start failed");
  `;

  for (const { screen, module } of [
    {
      screen: "the boundary above the router",
      module: /\/src\/App\.tsx|\/assets\/App-[\w-]+\.js/,
    },
    {
      screen: "the route tree's error page",
      module: /\/src\/pages\/LoginPage\.tsx|\/assets\/LoginPage-[\w-]+\.js/,
    },
  ]) {
    test(`${screen} does not end the navigation`, async ({ page }) => {
      let requests = 0;
      await page.route(module, (route) =>
        requests++ === 0
          ? route.fulfill({
              contentType: "text/javascript",
              body: FAILED_MODULE,
            })
          : route.continue(),
      );

      await page.goto("/login");

      expect(requests, "goto returned on the error screen").toBe(2);
    });
  }
});
