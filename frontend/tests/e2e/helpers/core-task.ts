import { type Locator, type Page } from "@playwright/test";
import { test, expect } from "../fixtures/auth";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "../fixtures/credentials";
import { ApiHelper } from "./api";
import {
  formatCount,
  growth,
  readBaseline,
  StepCounter,
  WRITING_BASELINE,
  writeBaselineEntry,
  type Viewport,
} from "./step-counts";

/**
 * What a core-task spec gets to seed and to check with. Seeding and the
 * checks at the end go through the API: the steps counted are the ones a
 * person takes in the browser, and the outcome is read where it lands.
 */
export interface StepEnv {
  api: ApiHelper;
  token: string;
  /** Unique per run and per worker, so names never collide between specs. */
  uid: string;
}

export interface StepTask<Seed> {
  /** The key in `core-task-steps.baseline.json`. Stable: renaming forks the history. */
  task: string;
  /** Sentence shown in the test report: what the person is doing. */
  title: string;
  /** The route the person is on when the task begins (nothing before it is counted). */
  start: string;
  /** Data the task needs; not counted. */
  seed: (env: StepEnv, viewport: Viewport) => Promise<Seed>;
  /**
   * The shortest path through the screens, written as the person takes it.
   * Every click, field and screen it passes is counted by the page itself.
   * It ends when the task is done on screen; the outcome is checked in `verify`.
   */
  walk: (
    page: Page,
    seed: Seed,
    viewport: Viewport,
    steps: StepCounter,
  ) => Promise<void>;
  /** The outcome read from the API: the task really did what it says. */
  verify: (env: StepEnv, seed: Seed, viewport: Viewport) => Promise<void>;
  /** Defaults to both. A task with no phone path says why in the spec. */
  viewports?: Viewport[];
}

const VIEWPORTS: Record<Viewport, { width: number; height: number }> = {
  desktop: { width: 1280, height: 800 },
  phone: { width: 390, height: 844 },
};

/**
 * Opens a location field with `name` on its list. The picker opens on the
 * first page of locations by name, which holds every location a person on a
 * clean database has; the shared test database holds more, so the name is
 * typed without counting it — the database's doing, not a step of the task.
 */
export async function openLocationField(
  field: Locator,
  name: string,
  steps: StepCounter,
): Promise<void> {
  await field.click();
  const search = field
    .page()
    .getByRole("dialog")
    .last()
    .getByRole("textbox", { name: /^Search/ });
  await steps.uncounted(async () => {
    await search.fill(name);
    // A text field reports its change when it loses focus, which would be
    // the counted click on the location; it is let go here instead.
    await search.blur();
  });
}

/**
 * One test per viewport: seed, open the start route, count the walk, check the
 * outcome, then compare the count with the baseline (or write it, when the
 * write-baseline command is the one running).
 *
 * The comparison fails when a count grows, with the metric named. A count that
 * shrinks passes and says so, so the baseline can be tightened on purpose.
 */
export function defineStepTask<Seed>(spec: StepTask<Seed>): void {
  const viewports = spec.viewports ?? (["desktop", "phone"] as Viewport[]);

  test.describe(`Core task — ${spec.title}`, () => {
    for (const viewport of viewports) {
      test.describe(viewport, () => {
        test.use({
          viewport: VIEWPORTS[viewport],
          hasTouch: viewport === "phone",
          isMobile: viewport === "phone",
        });

        test(`${spec.task}: steps on ${viewport}`, async ({
          page,
          playwright,
          baseURL,
          authenticatedPage,
        }, testInfo) => {
          // A whole task, seeded and walked screen by screen: on a loaded
          // machine a search alone took the rest of the default 30 s.
          test.setTimeout(90_000);
          void authenticatedPage;
          const ctx = await playwright.request.newContext({ baseURL });
          const api = new ApiHelper(ctx);
          const token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD))
            .access_token;
          await api.completeOnboarding(token);
          await api.enableAllModules(token);
          const env: StepEnv = {
            api,
            token,
            uid: `${Date.now().toString(36)}-w${testInfo.workerIndex}-${viewport[0]}`,
          };
          const seed = await spec.seed(env, viewport);

          const counter = new StepCounter(page);
          await counter.install();
          await page.goto(spec.start);
          await counter.begin();

          await spec.walk(page, seed, viewport, counter);
          const measured = await counter.read();
          await spec.verify(env, seed, viewport);
          await ctx.dispose();

          const label = `${spec.task} (${viewport})`;
          testInfo.annotations.push({
            type: "steps",
            description: `${label}: ${formatCount(measured)}`,
          });

          if (WRITING_BASELINE) {
            writeBaselineEntry(spec.task, viewport, measured);
            return;
          }

          const baseline = readBaseline()[spec.task]?.[viewport];
          const grown = growth(baseline, measured, label);
          expect(
            grown,
            baseline
              ? `${label} is longer than its baseline. Measured: ${formatCount(measured)}.` +
                  ` If the longer path is intended, say why in the change and run` +
                  ` npm run test:e2e:steps:write-baseline.`
              : `${label} has no baseline. Measured: ${formatCount(measured)}.`,
          ).toEqual([]);
        });
      });
    }
  });
}
