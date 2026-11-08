import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { transformWithOxc } from "vite";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The entry point is a script, not a component, so the way to ask whether it
 * still installs the reading-time rule is to run it and see the installer
 * called — not to read its text. A text match breaks on a change of indent and
 * stays green when the call is moved into a branch that never runs.
 *
 * `createRoot` is stubbed: what is pinned here is what `main.tsx` does as the
 * page loads, not what React draws afterwards.
 */
const installToastDefaults = vi.hoisted(() => vi.fn());
const render = vi.hoisted(() => vi.fn());

// The stylesheet is Tailwind source; jsdom cannot parse it and needs not.
vi.mock("./index.css", () => ({}));
vi.mock("./i18n/config", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  initI18n: () => Promise.resolve(),
}));
vi.mock("./lib/toastDefaults", () => ({ installToastDefaults }));
vi.mock("react-dom/client", () => ({
  default: { createRoot: () => ({ render }) },
}));

describe("the entry point", () => {
  beforeEach(() => {
    vi.resetModules();
    installToastDefaults.mockClear();
    render.mockClear();
    document.body.innerHTML = '<div id="root"></div>';
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("installs the reading-time rule that gives long messages their time", async () => {
    await import("./main");

    expect(installToastDefaults).toHaveBeenCalledTimes(1);
  });
});

/**
 * The entry module must never be run a second time by a hot update.
 *
 * `@vitejs/plugin-react` makes a module accept its own hot updates as soon as
 * React Refresh registers a component in it, and a lazy component counts.
 * `main.tsx` used to declare the two lazy trees itself, so every hot update
 * that climbed to it — a module's files landing under `src/modules` during an
 * install or an upgrade, an edit to `App.tsx` — ran it again: a second
 * `createRoot()` on the same container, two React trees writing one DOM, and
 * the error boundary catching what fell out of them until the page reloaded.
 *
 * A module that registers nothing is no boundary, so an update that reaches
 * it reloads the page instead, with one root. The transform below is the one
 * the dev server applies, with refresh on.
 */
describe("the entry point under hot updates", () => {
  it("registers no component with React Refresh", async () => {
    const file = resolve(__dirname, "main.tsx");
    const { code } = await transformWithOxc(readFileSync(file, "utf8"), file, {
      jsx: { runtime: "automatic", development: true, refresh: true },
    });

    expect(code).not.toContain("$RefreshReg$(");
  });
});
