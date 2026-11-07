import { test as playwrightTest } from '@playwright/test';

import { isTransientModuleLoadError } from '../helpers/transient-load';

/**
 * Chromium aborts in-flight requests with `net::ERR_NETWORK_CHANGED` whenever
 * the host's network changes — and on a host that runs docker, starting
 * another compose stack is enough. The dev server serves
 * one request per module, so a lazy route that was loading at that moment
 * ends on the error boundary, and no assertion about the page can pass.
 *
 * `import()` cannot recover on its own: the module map remembers a failed
 * dependency as failed. Only a reload clears it. The reload is capped, so a
 * module that is really broken still fails the test.
 *
 * Watching for the uncaught `import()` error alone missed most of it: a
 * production build hands the failure to the router, which logs it and shows
 * the error boundary without any uncaught error. The
 * abort hits the page's static module graph too (a blank page, no error
 * thrown), the app's own stale-chunk recovery (which shows "A new version is
 * ready" once its guard refuses a second reload) and API calls (a failed
 * module list leaves "Page Not Found" where the screen should be). Under a
 * churn of docker networks every failed request of a run carried this one
 * code, so the reload follows the abort itself. One reload per burst: a
 * change aborts dozens of module requests at once.
 */
const MAX_MODULE_LOAD_RELOADS = 2;
const NETWORK_CHANGED = 'net::ERR_NETWORK_CHANGED';

/**
 * What one start of the app may take before a spec's clock starts. The dev
 * server hands out about 500 modules per load: a second on a quiet host, 5.9 s
 * (median) to 10.5 s (worst of 100) with twelve workers at load 80. A recovery
 * reload starts all of it over, so the budget holds three starts.
 */
const APP_START_BUDGET = 35_000;

/**
 * The document has drawn past the app's full-screen loading state, to something
 * other than its error screen. The loading state starts in `index.html`, whose
 * own sign fills `#root` before any script has run, so a child in the root is
 * not a start: the sign carries the loader's test id for that reason. The error
 * screen is what a failed start looks like, and
 * the recovery reload comes after it, because the harness hears of the failure
 * only once it is drawn. A screen no reload clears costs a failing spec the
 * budget and is left to its assertion.
 */
const appHasStarted = () => {
  const root = document.getElementById('root');
  // Not one of the app's pages (a file, an API answer): nothing to wait for.
  if (!root) return true;
  return (
    root.childElementCount > 0 &&
    !document.querySelector('[data-testid="app-loading"], [data-testid="app-error"]')
  );
};

/**
 * The test every spec imports, directly or through a fixture file that
 * extends it (`auth`, `polish`). A spec that imports `test` from
 * `@playwright/test` itself misses the recovery, and a transient abort during
 * a lazy route load fails it.
 */
export const test = playwrightTest.extend({
  page: async ({ page }, use, testInfo) => {
    const goto = page.goto.bind(page);
    const reloadPage = page.reload.bind(page);
    let reloads = 0;
    let reloading = false;
    const reload = () => {
      if (reloading || reloads >= MAX_MODULE_LOAD_RELOADS) return;
      reloads++;
      reloading = true;
      // The start this reload repeats is not the test's to pay for.
      testInfo.setTimeout(testInfo.timeout + APP_START_BUDGET / 3);
      // Fire-and-forget: the page may close under us when the test ends.
      void reloadPage()
        .catch(() => {})
        .finally(() => {
          reloading = false;
        });
    };

    /**
     * Navigation returns at the `load` event, long before the app has drawn
     * anything: a spec's next wait was timing the app's start, and a recovery
     * reload inside it, instead of the thing it names. So a navigation ends
     * when the app has started (the wait outlives a reload), and the test gets
     * that time back. A page that never starts is left to the spec's own
     * assertion to report.
     */
    const started =
      <Args extends unknown[], Result>(navigate: (...args: Args) => Promise<Result>) =>
      async (...args: Args): Promise<Result> => {
        const begun = Date.now();
        testInfo.setTimeout(testInfo.timeout + APP_START_BUDGET);
        const result = await navigate(...args);
        await page
          .waitForFunction(appHasStarted, undefined, { timeout: APP_START_BUDGET })
          .catch(() => {});
        testInfo.setTimeout(testInfo.timeout - APP_START_BUDGET + (Date.now() - begun));
        return result;
      };
    page.goto = started(goto);
    page.reload = started(reloadPage);

    page.on('pageerror', (error) => {
      if (isTransientModuleLoadError(error.message)) reload();
    });
    // A lazy route whose chunk failed is caught by the router or the error
    // boundary, which is why no `pageerror` fires: the failure only shows in
    // the console. This is the form it takes in a production build.
    page.on('console', (message) => {
      if (message.type() === 'error' && isTransientModuleLoadError(message.text())) reload();
    });
    page.on('requestfailed', (request) => {
      if (request.failure()?.errorText === NETWORK_CHANGED) reload();
    });

    // What the page itself reported while the test ran. A start that ends on a
    // blank page leaves nothing else to attribute a timeout to: the assertion
    // only says the element never came. Kept for a failing test only, and
    // never used to retry or to excuse one.
    const diagnostics: string[] = [];
    const note = (kind: string, detail: string) =>
      diagnostics.push(`${new Date().toISOString()} ${kind} ${detail}`);
    page.on('pageerror', (error) => note('pageerror', error.message));
    page.on('console', (message) => {
      if (message.type() === 'error') note('console.error', message.text());
    });
    page.on('requestfailed', (request) =>
      note('requestfailed', `${request.method()} ${request.url()} ${request.failure()?.errorText ?? ''}`)
    );
    page.on('response', (response) => {
      if (response.status() >= 400) {
        note('response', `${response.status()} ${response.request().method()} ${response.url()}`);
      }
    });
    await use(page);
    if (testInfo.status !== testInfo.expectedStatus) {
      await testInfo.attach('page-diagnostics', {
        body: diagnostics.length
          ? diagnostics.join('\n')
          : 'no page errors, failed requests or 4xx/5xx answers were seen',
        contentType: 'text/plain'
      });
    }
  }
});

export { expect } from '@playwright/test';
