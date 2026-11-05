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
