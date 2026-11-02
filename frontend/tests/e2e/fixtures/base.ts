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
 * The test every spec imports, directly or through a fixture file that
 * extends it (`auth`, `polish`). A spec that imports `test` from
 * `@playwright/test` itself misses the recovery, and a transient abort during
 * a lazy route load fails it.
 */
export const test = playwrightTest.extend({
  page: async ({ page }, use) => {
    let reloads = 0;
    let reloading = false;
    const reload = () => {
      if (reloading || reloads >= MAX_MODULE_LOAD_RELOADS) return;
      reloads++;
      reloading = true;
      // Fire-and-forget: the page may close under us when the test ends.
      void page
        .reload()
        .catch(() => {})
        .finally(() => {
          reloading = false;
        });
    };
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
    await use(page);
  }
});

export { expect } from '@playwright/test';
