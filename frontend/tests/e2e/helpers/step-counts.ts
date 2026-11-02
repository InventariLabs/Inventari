import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";

/**
 * How long a core task is, counted the way the person doing it feels it.
 *
 * A task's length is three numbers: the clicks it takes, the distinct fields
 * typed into (or chosen from) and the screens it passes through. They are
 * counted in the page, from the events the browser itself raises, and not
 * from the calls a spec makes, so a spec cannot undercount by reaching for a
 * shortcut and a redesign that adds a confirmation sheet is seen even when
 * the spec was written before it.
 *
 * - **clicks** — trusted `click` events. A label forwarding a click to its
 *   input raises an untrusted one and is not counted twice.
 * - **fields** — distinct elements that raised an `input` or `change` event.
 *   Typing in one box for the length of a sentence is one field; a native
 *   `<select>` chosen from is one field.
 * - **screens** — distinct routes visited, the first included. A query
 *   string, a sheet or a dialog opening over the same route is not a screen.
 *
 * The counts live in `core-task-steps.baseline.json`. The gate fails when one
 * of them grows; `npm run test:e2e:steps:write-baseline` is the only way to
 * change the file.
 */

export type Viewport = "desktop" | "phone";

export interface StepCount {
  clicks: number;
  fields: number;
  screens: number;
}

export type StepBaseline = Record<string, Partial<Record<Viewport, StepCount>>>;

/** The ten core tasks. Adding to this list is how an eleventh joins the gate. */
export const CORE_TASKS = [
  "receive-delivery",
  "receive-from-order",
  "issue-to-customer",
  "move-between-locations",
  "count-a-shelf",
  "undo-a-mistake",
  "find-a-product",
  "record-i-made-it",
  "add-first-product",
  "approve-a-document",
] as const;

const METRICS = ["clicks", "fields", "screens"] as const;

const BASELINE_PATH = fileURLToPath(
  new URL("../core-task-steps.baseline.json", import.meta.url),
);

/** Set by the write-baseline script; no other path rewrites the baseline. */
export const WRITING_BASELINE = process.env.STEP_COUNTS_WRITE_BASELINE === "1";

const STORE_KEY = "__e2eStepCount";

/**
 * Runs in the page before the app does. State lives in `sessionStorage`, so a
 * full reload in the middle of a task keeps counting instead of starting over.
 */
function recorder(storeKey: string) {
  type State = {
    active: boolean;
    paused?: boolean;
    clicks: number;
    fields: string[];
    screens: string[];
  };
  const read = (): State => {
    try {
      const raw = sessionStorage.getItem(storeKey);
      if (raw) return JSON.parse(raw) as State;
    } catch {
      /* fall through to a fresh state */
    }
    return { active: false, clicks: 0, fields: [], screens: [] };
  };
  const write = (state: State) => {
    try {
      sessionStorage.setItem(storeKey, JSON.stringify(state));
    } catch {
      /* a page without storage counts nothing, and the spec says so */
    }
  };
  // Elements get a stable name the first time they are typed into.
  const names = new WeakMap<EventTarget, string>();
  let nextName = 0;
  const nameOf = (target: EventTarget) => {
    let name = names.get(target);
    if (!name) {
      name = `${location.pathname}#${nextName++}`;
      names.set(target, name);
    }
    return name;
  };

  document.addEventListener(
    "click",
    (event) => {
      const state = read();
      if (!state.active || state.paused || !event.isTrusted) return;
      state.clicks += 1;
      write(state);
    },
    true,
  );
  const onField = (event: Event) => {
    const state = read();
    if (!state.active || state.paused || !event.target) return;
    const name = nameOf(event.target);
    if (!state.fields.includes(name)) state.fields.push(name);
    write(state);
  };
  document.addEventListener("input", onField, true);
  document.addEventListener("change", onField, true);

  const route = () => {
    const state = read();
    if (!state.active || state.paused) return;
    if (state.screens[state.screens.length - 1] === location.pathname) return;
    state.screens.push(location.pathname);
    write(state);
  };
  for (const method of ["pushState", "replaceState"] as const) {
    const original = history[method].bind(history);
    history[method] = (...args: Parameters<History["pushState"]>) => {
      original(...args);
      route();
    };
  }
  window.addEventListener("popstate", route);
}

/** Counts one task's steps on one page. */
export class StepCounter {
  constructor(private readonly page: Page) {}

  /** Before the first `goto`: the recorder has to be there before the app. */
  async install(): Promise<void> {
    await this.page.addInitScript(recorder, STORE_KEY);
  }

  /**
   * The task starts here: whatever was typed or clicked to get this far is
   * set-up, not the task. The screen the page is on counts as the first one.
   *
   * A page can reload itself once just after it loaded — the app does when
   * a busy dev server fails a module request (`src/lib/staleChunk.ts`) — and
   * the reload takes the evaluation with it. The task then starts on the
   * page that stays.
   */
  async begin(): Promise<void> {
    const start = ([key]: string[]) => {
      sessionStorage.setItem(
        key,
        JSON.stringify({
          active: true,
          clicks: 0,
          fields: [],
          screens: [location.pathname],
        }),
      );
    };
    try {
      await this.page.evaluate(start, [STORE_KEY]);
    } catch (error) {
      if (!/Execution context was destroyed/.test(String(error))) throw error;
      await this.page.waitForLoadState();
      await this.page.evaluate(start, [STORE_KEY]);
    }
  }

  /**
   * Runs `work` without counting it. For what a shared test database adds to
   * the screen and a person on a clean one would never do — pressing "Show
   * more" to find a task among a hundred older ones. Never for a step the
   * task itself needs.
   */
  async uncounted<T>(work: () => Promise<T>): Promise<T> {
    await this.setPaused(true);
    try {
      return await work();
    } finally {
      await this.setPaused(false);
    }
  }

  private async setPaused(paused: boolean): Promise<void> {
    await this.page.evaluate(
      ([key, value]) => {
        const raw = sessionStorage.getItem(key as string);
        if (!raw) return;
        const state = JSON.parse(raw);
        state.paused = value;
        sessionStorage.setItem(key as string, JSON.stringify(state));
      },
      [STORE_KEY, paused] as const,
    );
  }

  async read(): Promise<StepCount> {
    const raw = await this.page.evaluate(
      ([key]) => sessionStorage.getItem(key),
      [STORE_KEY],
    );
    if (!raw) throw new Error("The step counter was not begun on this page");
    const state = JSON.parse(raw) as {
      clicks: number;
      fields: string[];
      screens: string[];
    };
    return {
      clicks: state.clicks,
      fields: state.fields.length,
      screens: state.screens.length,
    };
  }
}

/** The metrics that grew past the baseline, as lines a failure can print. */
export function growth(
  baseline: StepCount | undefined,
  measured: StepCount,
  label: string,
): string[] {
  if (!baseline) {
    return [
      `${label}: no baseline yet (${formatCount(measured)}) — run npm run test:e2e:steps:write-baseline`,
    ];
  }
  return METRICS.filter((metric) => measured[metric] > baseline[metric]).map(
    (metric) =>
      `${label}: ${metric} grew from ${baseline[metric]} to ${measured[metric]}`,
  );
}

export function formatCount(count: StepCount): string {
  return `${count.clicks} clicks, ${count.fields} fields, ${count.screens} screens`;
}

export function readBaseline(path = BASELINE_PATH): StepBaseline {
  if (!existsSync(path)) return {};
  return JSON.parse(readFileSync(path, "utf8")) as StepBaseline;
}

/** Merges one measurement into the baseline file, keys sorted for a stable diff. */
export function writeBaselineEntry(
  task: string,
  viewport: Viewport,
  count: StepCount,
  path = BASELINE_PATH,
): void {
  const baseline = readBaseline(path);
  baseline[task] = { ...baseline[task], [viewport]: count };
  const sorted = Object.fromEntries(
    Object.keys(baseline)
      .sort()
      .map((name) => [name, baseline[name]]),
  );
  writeFileSync(path, `${JSON.stringify(sorted, null, 2)}\n`);
}
