/**
 * The anonymous tree must not import the application. These specs build a
 * small `src/` and run the gate over it, so what is pinned is the sentence a
 * failing build prints, not the walker's internals.
 */
import { afterEach, describe, expect, it } from "vitest";

import { makeRepo, runGate } from "./gate-fixture.mjs";

const src = (files) =>
  Object.fromEntries(
    Object.entries(files).map(([name, text]) => [`frontend/src/${name}`, text]),
  );

const CLEAN = {
  "PublicApp.tsx":
    'import { routes } from "./publicRoutes";\nexport default routes;\n',
  "publicRoutes.ts":
    'import { thanks } from "./lib/thanks";\nexport const routes = thanks;\n',
  "lib/thanks.ts": "export const thanks = 1;\n",
  "App.tsx": 'import "./lib/moduleRegistry";\nexport default 1;\n',
  "lib/moduleRegistry.ts": "export const registry = {};\n",
  "modules/stock/module.ts":
    'import { registry } from "../../lib/moduleRegistry";\n',
};

let repo;
afterEach(() => repo?.cleanup());

const run = (files) => {
  repo = makeRepo();
  repo.write(src(files));
  return runGate(repo, "check-public-bundle.mjs", {
    siblings: ["check-reachability.mjs"],
  });
};

describe("check-public-bundle", () => {
  it("passes when the anonymous tree stays out of the app, and counts what it reaches", () => {
    const { status, stdout } = run(CLEAN);

    expect(status).toBe(0);
    expect(stdout).toContain("reaches 3 source file(s)");
  });

  it("fails when an entry imports App, and prints the path that got there", () => {
    const { status, stderr } = run({
      ...CLEAN,
      "lib/thanks.ts":
        'import App from "../App";\nexport const thanks = App;\n',
    });

    expect(status).toBe(1);
    expect(stderr).toContain("reaches");
    expect(stderr).toContain("App.tsx");
    expect(stderr).toContain(
      "reached via: publicRoutes.ts -> lib/thanks.ts -> App.tsx",
    );
  });

  it("fails on the module registry, even through a dynamic import", () => {
    const { status, stderr } = run({
      ...CLEAN,
      "publicRoutes.ts":
        'export const load = () => import("./lib/moduleRegistry");\n',
    });

    expect(status).toBe(1);
    expect(stderr).toContain("lib/moduleRegistry.ts");
    expect(stderr).toContain("modules register themselves into it on import");
  });

  it("fails on a module's registration file, through the @/ alias", () => {
    const { status, stderr } = run({
      ...CLEAN,
      "PublicApp.tsx": 'import "@/modules/stock/module";\n',
    });

    expect(status).toBe(1);
    expect(stderr).toContain("a module's registration file");
  });

  it("does not follow a bare package import out of src", () => {
    const { status } = run({
      ...CLEAN,
      "PublicApp.tsx": 'import "react";\nimport "./publicRoutes";\n',
    });

    expect(status).toBe(0);
  });

  it("fails loudly, not green, when an entry point has been renamed away", () => {
    const rest = { ...CLEAN };
    delete rest["PublicApp.tsx"];

    const { status, stderr } = run(rest);

    expect(status).toBe(1);
    expect(stderr).toContain("entry point PublicApp.tsx does not exist");
  });
});
