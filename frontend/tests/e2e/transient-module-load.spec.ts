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
