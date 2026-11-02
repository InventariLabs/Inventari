import { test, expect } from "./fixtures/auth";
import {
  CORE_TASKS,
  growth,
  readBaseline,
  StepCounter,
  type StepCount,
} from "./helpers/step-counts";

/**
 * The step counter and the gate built on it, tested on their own.
 *
 * The ten tasks (`core-task-steps-*.spec.ts`) fail when a count grows; this
 * file is what makes that failure believable: the counter sees a click, a
 * typed field and a screen when the page raises them, the comparison names
 * the metric that grew, and the committed baseline holds every task on both
 * viewports, so a task cannot be dropped to make the gate green.
 */

const BASE: StepCount = { clicks: 6, fields: 3, screens: 2 };

test.describe("Step-count gate", () => {
  test("a path that is as long as its baseline passes", () => {
    expect(growth(BASE, { ...BASE }, "task (desktop)")).toEqual([]);
  });

  test("a path that is shorter than its baseline passes", () => {
    expect(
      growth(BASE, { clicks: 5, fields: 3, screens: 2 }, "task (desktop)"),
    ).toEqual([]);
  });

  test("one extra click fails and names the metric", () => {
    expect(
      growth(BASE, { ...BASE, clicks: BASE.clicks + 1 }, "task (desktop)"),
    ).toEqual(["task (desktop): clicks grew from 6 to 7"]);
  });

  test("one extra typed field or one extra screen fails the same way", () => {
    expect(
      growth(BASE, { ...BASE, fields: BASE.fields + 1 }, "task (phone)"),
    ).toEqual(["task (phone): fields grew from 3 to 4"]);
    expect(
      growth(BASE, { ...BASE, screens: BASE.screens + 1 }, "task (phone)"),
    ).toEqual(["task (phone): screens grew from 2 to 3"]);
  });

  test("a task with no baseline fails instead of passing unmeasured", () => {
    const lines = growth(undefined, BASE, "task (desktop)");
    expect(lines).toHaveLength(1);
    expect(lines[0]).toContain("no baseline yet");
  });

  test("the baseline holds all ten tasks on both viewports", () => {
    const baseline = readBaseline();
    expect(Object.keys(baseline).sort()).toEqual([...CORE_TASKS].sort());
    for (const task of CORE_TASKS) {
      for (const viewport of ["desktop", "phone"] as const) {
        const count = baseline[task]?.[viewport];
        expect(count, `${task} (${viewport})`).toBeDefined();
        // A task can need no typing (fields 0), but not no click or no screen.
        expect(count?.clicks, `${task} (${viewport}) clicks`).toBeGreaterThan(
          0,
        );
        expect(count?.screens, `${task} (${viewport}) screens`).toBeGreaterThan(
          0,
        );
        expect(
          count?.fields,
          `${task} (${viewport}) fields`,
        ).toBeGreaterThanOrEqual(0);
      }
    }
  });

  test("the counter sees a click, a typed field and a screen in a real page", async ({
    page,
    authenticatedPage,
  }) => {
    const counter = new StepCounter(page);
    await counter.install();
    await page.goto("/warehouse/todo");
    await counter.begin();
    expect(await counter.read()).toEqual({
      clicks: 0,
      fields: 0,
      screens: 1,
    });

    // One click, one new screen.
    await page
      .getByRole("navigation", { name: "Module navigation" })
      .getByRole("link", { name: "History" })
      .click();
    await expect(page).toHaveURL(/\/warehouse\/history/);
    expect(await counter.read()).toEqual({
      clicks: 1,
      fields: 0,
      screens: 2,
    });

    // Typing twice into one box is one field; the click into it is a click.
    const search = page
      .getByRole("searchbox")
      .or(page.getByRole("textbox"))
      .first();
    await search.click();
    await search.fill("a");
    await search.fill("ab");
    const typed = await counter.read();
    expect(typed.fields).toBe(1);
    expect(typed.clicks).toBe(2);
    expect(typed.screens).toBe(2);
  });
});
