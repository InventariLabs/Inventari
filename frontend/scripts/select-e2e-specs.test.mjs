/**
 * What must hold: a diff selects every browser spec it can break — changed,
 * importing a changed file, spelling a removed text, or driving a changed
 * module — and a change to the shared shell selects them all. The run goes
 * project by project in the order the Playwright config requires.
 */
import { chmodSync, readFileSync } from "node:fs";
import { delimiter, join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import config from "../playwright.config";
import { makeRepo, runGate } from "./gate-fixture.mjs";
import { PHASES, selectSpecs } from "./select-e2e-specs.mjs";

const spec = (name) => `tests/e2e/${name}.spec.ts`;

const FILES = {
  [spec("equipment")]: "",
  [spec("equipment-pentest")]: "",
  [spec("assets")]: 'await page.goto("/equipment/assets");',
  [spec("detail")]: "await page.goto(`${BASE}/equipment/assets/${id}`);",
  [spec("address")]:
    "await expect(page).toHaveURL(/\\/equipment\\/assets\\/[a-f0-9-]+$/);",
  [spec("prefix-only")]: 'await page.goto("/equipment/assets-old/x/y");',
  [spec("purchase-orders")]: "",
  [spec("items")]:
    'import { seed } from "./helpers/receive-seed";\n// page.goto("/equipment/assets")',
  [spec("labels")]: 'import { seed } from "./helpers/other";',
  [spec("a11y")]: 'import { counts } from "./helpers/counts";',
  "tests/e2e/helpers/receive-seed.ts": 'import { api } from "./api";',
  "tests/e2e/helpers/api.ts": 'import x from "../../../src/lib/staleChunk";',
  "tests/e2e/helpers/other.ts": "",
  "tests/e2e/helpers/counts.ts": 'readFileSync("../steps.baseline.json");',
  "src/lib/staleChunk.ts": "",
  "src/modules/equipment/module.ts": [
    'moduleRegistry.register({ moduleNav: { basePath: "/equipment" },',
    '  routes: [{ path: "/equipment/assets" }, { path: "/equipment/assets/:id" }] });',
  ].join("\n"),
};

const SPECS = Object.keys(FILES).filter((path) => path.endsWith(".spec.ts"));

function select(changed, options = {}) {
  const { full, specs } = selectSpecs({
    changed,
    specs: SPECS,
    read: (path) => FILES[path] ?? null,
    ...options,
  });
  return { full, names: [...specs.keys()].sort(), specs };
}

const named = (...names) => names.map(spec).sort();

describe("selectSpecs", () => {
  it("selects a changed spec and nothing else", () => {
    expect(select([`frontend/${spec("labels")}`]).names).toEqual(
      named("labels"),
    );
  });

  it("selects the specs that import a changed helper, however far", () => {
    for (const changed of [
      "frontend/tests/e2e/helpers/receive-seed.ts",
      "frontend/tests/e2e/helpers/api.ts",
      "frontend/src/lib/staleChunk.ts",
    ])
      expect(select([changed]).names).toEqual(named("items"));
  });

  it("selects the importers of a deleted helper", () => {
    const { specs } = selectSpecs({
      changed: ["frontend/tests/e2e/helpers/other.ts"],
      specs: SPECS,
      read: (path) =>
        path === "tests/e2e/helpers/other.ts" ? null : (FILES[path] ?? null),
    });
    expect([...specs.keys()]).toEqual(named("labels"));
  });

  it("selects the specs that read a changed data file", () => {
    expect(select(["frontend/tests/e2e/steps.baseline.json"]).names).toEqual(
      named("a11y"),
    );
  });

  it("selects the specs that spell a removed text, helpers' importers too", () => {
    const stale = [
      { spec: spec("labels"), old: "Vision AI" },
      { spec: "tests/e2e/helpers/api.ts", old: "Check in" },
    ];
    expect(select([], { stale }).names).toEqual(named("items", "labels"));
  });

  it("selects a module's specs by name and by the routes they open", () => {
    const expected = named(
      "address",
      "assets",
      "detail",
      "equipment",
      "equipment-pentest",
    );
    expect(
      select(["frontend/src/modules/equipment/pages/X.tsx"]).names,
    ).toEqual(expected);
    expect(
      select(["backend/app/modules/equipment/service.py"]).names,
    ).toEqual(expected);
  });

  it("names a module's specs with hyphens", () => {
    expect(
      select(["backend/app/modules/purchase_orders/routes.py"]).names,
    ).toEqual(named("purchase-orders"));
  });

  it("selects nothing for a module's tests, documents and translations", () => {
    expect(
      select([
        "frontend/src/modules/equipment/pages/X.test.tsx",
        "frontend/src/modules/equipment/__tests__/helpers.ts",
        "frontend/src/modules/equipment/i18n/de.json",
        "backend/app/modules/equipment/README.md",
        "backend/tests/integration/test_equipment.py",
        "CHANGELOG.md",
      ]).names,
    ).toEqual([]);
  });

  it("selects the whole suite for the shared shell", () => {
    for (const changed of [
      "frontend/playwright.config.ts",
      "frontend/tests/e2e/fixtures/base.ts",
      "frontend/tests/e2e/globalSetup.ts",
      "frontend/src/App.tsx",
      "frontend/src/lib/moduleRegistry.ts",
      "frontend/src/lib/moduleRegistry/registry.ts",
      "frontend/src/components/AppShell.tsx",
      "frontend/src/components/shell/UserMenu.tsx",
    ]) {
      const result = select([changed]);
      expect(result.full, changed).toEqual([changed]);
      expect(result.names, changed).toEqual([...SPECS].sort());
    }
  });

  it("keeps a test of the shell and an ordinary component narrow", () => {
    expect(
      select([
        "frontend/src/App.scanRedirect.test.tsx",
        "frontend/src/lib/moduleRegistry/registry.test.ts",
        "frontend/src/components/shell/UserMenu.test.tsx",
        "frontend/src/components/ThemeToggle.tsx",
      ]),
    ).toMatchObject({ full: [], names: [] });
  });
});

describe("PHASES", () => {
  it("runs every project once, after the projects it depends on", () => {
    const order = PHASES.flat();
    expect([...order].sort()).toEqual(
      config.projects.map((project) => project.name).sort(),
    );
    for (const { name, dependencies = [] } of config.projects) {
      const phase = PHASES.findIndex((names) => names.includes(name));
      for (const before of dependencies)
        expect(
          PHASES.findIndex((names) => names.includes(before)),
          `${name} after ${before}`,
        ).toBeLessThan(phase);
    }
  });
});

describe("the script as a process", () => {
  let repo;
  afterEach(() => {
    vi.unstubAllEnvs();
    repo.cleanup();
  });

  /**
   * Run it on a scratch tree. The frontend container has no git, so stand-ins
   * answer for git and for `npx playwright`, which records what it was asked.
   */
  function run(args, { changed, red = "" }) {
    repo = makeRepo();
    const calls = join(repo.root, "calls");
    const stand = (body) => `#!${process.execPath}\n${body}\n`;
    repo.write({
      [`frontend/${spec("approvals")}`]: "",
      [`frontend/${spec("items")}`]: "",
      "frontend/src/i18n/locales/en/common.json": {},
      "frontend/src/modules/items/module.ts": "",
      "bin/git": stand(
        `const [command] = process.argv.slice(2);
         process.stdout.write({ "merge-base": "abc\\n", diff: command === "diff" && process.argv.includes("--relative") ? "" : ${JSON.stringify(changed.join("\n"))} }[command]);`,
      ),
      "bin/npx": stand(
        `const args = process.argv.slice(2);
         require("node:fs").appendFileSync(${JSON.stringify(calls)}, args.join(" ") + "\\n");
         if (args.includes("--list"))
           console.log("  [approvals] › approvals.spec.ts:1 › a\\n  [chromium] › items.spec.ts:1 › b");
         process.exit(${JSON.stringify(red)} && args.includes("--project=" + ${JSON.stringify(red)}) ? 1 : 0);`,
      ),
    });
    for (const name of ["git", "npx"])
      chmodSync(join(repo.root, "bin", name), 0o755);
    vi.stubEnv(
      "PATH",
      `${join(repo.root, "bin")}${delimiter}${process.env.PATH}`,
    );
    const result = runGate(repo, "select-e2e-specs.mjs", {
      args,
      siblings: ["check-e2e-catalog-text.mjs", "source-text.mjs"],
    });
    let asked = [];
    try {
      asked = readFileSync(calls, "utf8").trim().split("\n");
    } catch {
      // Playwright was not called.
    }
    return { ...result, asked };
  }

  const both = [`frontend/${spec("items")}`, `frontend/${spec("approvals")}`];

  it("prints the selection and runs nothing without --run", () => {
    const result = run([], { changed: both });
    expect(result.status).toBe(0);
    expect(result.stdout).toBe(`${spec("approvals")}\n${spec("items")}\n`);
    expect(result.asked).toEqual([]);
  });

  it("runs each project alone, in order, without its dependencies", () => {
    const result = run(["--run"], { changed: both, red: "chromium" });
    expect(result.status).toBe(1);
    expect(result.stderr).toContain("red in chromium");
    const runs = result.asked.filter((line) => !line.includes("--list"));
    expect(runs.map((line) => line.match(/--project=\S+/g))).toEqual([
      ["--project=chromium"],
      ["--project=approvals"],
    ]);
    for (const line of runs) {
      expect(line).toContain("--no-deps");
      expect(line).toContain(`${spec("approvals")} ${spec("items")}`);
    }
  });

  it("runs the suite as the config orders it when the shell changed", () => {
    const result = run(["--run"], { changed: ["frontend/src/App.tsx"] });
    expect(result.status).toBe(0);
    expect(result.asked).toEqual(["playwright test --reporter=list"]);
  });

  it("runs nothing for an empty selection", () => {
    const result = run(["--run"], { changed: ["CHANGELOG.md"] });
    expect(result.status).toBe(0);
    expect(result.asked).toEqual([]);
  });

  it("exits 2 when the base cannot be read", () => {
    repo = makeRepo();
    const result = runGate(repo, "select-e2e-specs.mjs", {
      args: ["--base", "no-such-ref"],
      siblings: ["check-e2e-catalog-text.mjs", "source-text.mjs"],
    });
    expect(result.status).toBe(2);
  });
});
