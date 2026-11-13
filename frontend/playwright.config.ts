import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";

/**
 * Workers for this machine, from the script the Makefile and CI ask for the
 * pytest count too: cores and free memory, a container's cgroup limits
 * included. Eight fixed workers on a two-CPU runner starved the browsers and
 * the servers under test alike. `PLAYWRIGHT_WORKERS` overrides one run;
 * without Python (a tool that only reads this file) Playwright's own default
 * applies.
 */
function machineWorkers(): number | undefined {
  if (process.env.PLAYWRIGHT_WORKERS)
    return Number(process.env.PLAYWRIGHT_WORKERS);
  try {
    const script = fileURLToPath(
      new URL("../scripts/test-workers.py", import.meta.url),
    );
    return Number(
      execFileSync("python3", [script, "playwright"], {
        encoding: "utf8",
      }).trim(),
    );
  } catch {
    return undefined;
  }
}

/**
 * See https://playwright.dev/docs/test-configuration.
 */
export default defineConfig({
  globalSetup: "./tests/e2e/globalSetup.ts",
  globalTeardown: "./tests/e2e/globalTeardown.ts",
  testDir: "./tests/e2e",
  /* Maximum time one test can run for. */
  timeout: 30 * 1000,
  expect: {
    timeout: 5000,
  },
  /* Run tests in files in parallel */
  fullyParallel: true,
  workers: machineWorkers(),
  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: !!process.env.CI,
  /* Retry on CI only */
  retries: process.env.CI ? 2 : 1,
  /* Reporter to use. See https://playwright.dev/docs/test-reporters */
  reporter: "html",
  /* Shared settings for all the projects below. See https://playwright.dev/docs/api/class-testoptions. */
  use: {
    /* Base URL to use in actions like `await page.goto('/')`. */
    baseURL: process.env.VITE_API_URL || "http://127.0.0.1:5173",

    /* Per-test auth is handled by fixtures/auth.ts — no shared storageState. */

    /* Collect trace when retrying the failed test. See https://playwright.dev/docs/trace-viewer */
    trace: "on-first-retry",
    video: "on-first-retry",
    screenshot: "only-on-failure",

    /* Force English locale so all test selectors match English UI text */
    locale: "en-US",

    /* Attribute used for data-testid */
    testIdAttribute: "data-testid",
  },

  /* Configure projects for major browsers */
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      // Specs that rewrite org-wide state belong to `org-profile`,
      // `module-gate`, `approvals`, `value-tracking` and `announcements` below.
      // `phone-first-record-responsive` is the phone's alone: it seeds and
      // removes organization-wide rows (the built-in templates) that a second
      // project running it side by side would pull from under it.
      testIgnore:
        /((warehouse-location-)?workspace-mode|maker-module-gate|approvals(-integration)?|announcement-publish|example-module|warehouse-office-output|warehouse-reduced-rates|phone-first-record-responsive)\.spec\.ts/,
    },
    {
      // Opt-in by file name: a spec whose name ends in `responsive` runs on
      // the phone as well as on the desktop (`chromium`), on purpose.
      name: "mobile",
      use: { ...devices["iPhone 14"] },
      testMatch: /.*(responsive|auth|dashboard|scan-camera)\.spec\.ts/,
    },
    {
      // The only project that renders the app in Polish. Narrow on purpose:
      // login, documents list, document detail, shopping list. Phone viewport
      // because that is the priority form factor for this product.
      name: "pl-PL",
      use: { ...devices["iPhone 14"], locale: "pl-PL" },
      testMatch: /.*polish-ui\.spec\.ts/,
    },
    {
      // Switching the org's product profile rewrites
      // `Organization.enabled_modules` for the whole tenant — and every worker
      // shares that one tenant, because registration is invite-only
      // and cannot mint a second org. While the switch is applied (~2s, until
      // the spec restores the original profile) every module outside the
      // target profile answers 403: an `equipment` spec that started its
      // fixtures inside that window died on
      // "Module 'equipment' is not enabled for this organization".
      //
      // So these specs get the stack to themselves, after every other project,
      // and one at a time: two of them each switch the profile and back, and
      // side by side one read the other's switch — a business walk that met
      // the household's codes and a 403 from a warehouse just switched off.
      // Playwright skips a project whose dependency failed — an accepted trade
      // for not flaking the ~600 tests that just want a stable module list.
      //
      // Two files switch the profile: `workspace-mode` and
      // `warehouse-location-workspace-mode`. The pattern names both, so the
      // second one is here on purpose, and `workers: 1` keeps them from
      // running side by side. A new spec that calls the profile switch joins
      // this pattern and the `chromium` ignore list above.
      //
      // To iterate on these specs alone, pass --no-deps; without it, filtering
      // by file still runs every dependency project in full.
      name: "org-profile",
      use: { ...devices["Desktop Chrome"] },
      testMatch: /(warehouse-location-)?workspace-mode\.spec\.ts/,
      workers: 1,
      dependencies: [
        "chromium",
        "mobile",
        "pl-PL",
        "module-gate",
        "approvals",
        "approvals-mobile",
        "value-tracking",
        "announcements",
      ],
    },
    {
      // Switching a module off is the same kind of write, narrower: while
      // maker is off every maker endpoint answers 403, so a production list in
      // another worker stays on its loading state while the query retries and
      // the dashboard never renders the result widget. Two specs did it from
      // inside `chromium`, and two maker-result tests failed in every full run
      // while passing alone. After `chromium` and before `org-profile`, so the
      // two rewrites of the module list never overlap either. `mobile` and
      // `pl-PL` have no dependencies, so they run in the first phase, and
      // Playwright finishes a phase before it starts the next: they are done
      // before this project starts and can call `enableAllModules` freely (the
      // phone's `phone-first-record-responsive` does). `approvals` waits for
      // this project.
      name: "module-gate",
      use: { ...devices["Desktop Chrome"] },
      testMatch: /maker-module-gate\.spec\.ts/,
      dependencies: ["chromium"],
    },
    {
      // Approval workflows apply to every document of the org, and these
      // specs create them, and delete all of them in their `beforeAll`. A
      // workflow alive while a documents spec in another worker confirms
      // turns that confirm into PENDING_APPROVAL ("APPROVAL_REQUIRED"); and
      // one approvals describe's org-wide cleanup deleted the workflow another
      // describe had just created. So they run after `chromium`, in one
      // worker. They run after `module-gate` too: their setup calls
      // `enableAllModules`, which switches maker on, and running alongside it
      // would undo the switch-off the gate tests assert on.
      name: "approvals",
      use: { ...devices["Desktop Chrome"] },
      testMatch: /approvals(-integration)?\.spec\.ts/,
      testIgnore: /(^|\/)phone-approvals\.spec\.ts$/,
      dependencies: ["chromium", "module-gate"],
      workers: 1,
    },
    {
      // The approval lists on a phone: the same org-wide workflow as above,
      // so they run after `approvals`, alone, but on the phone project's
      // device like the rest of the phone list checks.
      name: "approvals-mobile",
      use: { ...devices["iPhone 14"] },
      testMatch: /(^|\/)phone-approvals\.spec\.ts$/,
      dependencies: ["chromium", "approvals"],
      workers: 1,
    },
    {
      // Tracking value is a setting of the whole organisation, and the office
      // output spec turns it on: while it is on, every receipt sheet draws its
      // price column and the unpriced-lines notice, and the totals count what
      // they would not. So it runs once the specs that read those screens
      // have finished, and not alongside an approval workflow that would hold
      // its posts.
      name: "value-tracking",
      use: { ...devices["Desktop Chrome"] },
      testMatch: /(warehouse-office-output|warehouse-reduced-rates)\.spec\.ts/,
      dependencies: [
        "chromium",
        "mobile",
        "pl-PL",
        "module-gate",
        "approvals",
        "approvals-mobile",
      ],
      workers: 1,
    },
    {
      // An announcement is installation-wide: while one exists, every screen
      // of every worker draws the banner above its content, and the specs
      // that count buttons or measure layout see one more of each. So the
      // spec that publishes them runs once everything else has finished, and
      // before `org-profile`, whose profile switch rewrites the module list
      // the banner's slot is drawn from.
      name: "announcements",
      use: { ...devices["Desktop Chrome"] },
      testMatch: /announcement-publish\.spec\.ts/,
      dependencies: [
        "chromium",
        "mobile",
        "pl-PL",
        "module-gate",
        "approvals",
        "approvals-mobile",
        "value-tracking",
      ],
    },
    // The guide's example module is not part of the platform: its spec needs
    // the module installed in the stack under test, which
    // `make e2e-example-module` does around it. Outside that target there is
    // no such project, so a full run neither runs the spec nor skips it.
    ...(process.env.E2E_EXAMPLE_MODULE
      ? [
          {
            name: "example-module",
            use: { ...devices["Desktop Chrome"] },
            testMatch: /example-module\.spec\.ts/,
            workers: 1,
          },
        ]
      : []),
  ],

  /* Run your local dev server before starting the tests */
  // webServer: {
  //   command: 'npm run dev',
  //   url: 'http://localhost:5173',
  //   reuseExistingServer: !process.env.CI,
  // },
});
