/**
 * The store catalog snapshot gate: every module the API returns must be in the
 * frontend's list of what the App Store has to show, and vice versa, wherever
 * both trees are visible.
 */
import { afterEach, describe, expect, it } from "vitest";

import { makeRepo, runGate } from "./gate-fixture.mjs";

const SNAPSHOT = "frontend/scripts/module-catalog.json";
const MODULES_API = "backend/app/api/modules.py";
const api = (...virtual) =>
  [
    "def available():",
    "    virtual_modules = [",
    ...virtual.map((name) => `        ModuleInfo(name='${name}'),`),
    "    ]",
    "",
  ].join("\n");
const manifest = (name, extra = {}) => ({
  [`backend/app/modules/${name}/manifest.json`]: { name, ...extra },
});

let repo;
afterEach(() => repo?.cleanup());

const run = (args = []) => runGate(repo, "check-module-catalog.mjs", { args });

describe("check-module-catalog", () => {
  it("passes when the snapshot is the real modules plus the virtual ones", () => {
    repo = makeRepo();
    repo.write({
      [MODULES_API]: api("core_tools"),
      ...manifest("recipes"),
      ...manifest("labels"),
      [SNAPSHOT]: ["core_tools", "labels", "recipes"],
    });

    const { status, stdout } = run();

    expect(status).toBe(0);
    expect(stdout).toContain(
      "3 module(s) the store must show, snapshot matches",
    );
  });

  it("leaves a reference module out: a worked example is not a product", () => {
    repo = makeRepo();
    repo.write({
      [MODULES_API]: api(),
      ...manifest("recipes"),
      ...manifest("example", { is_reference: true }),
      [SNAPSHOT]: ["recipes"],
    });

    expect(run().status).toBe(0);
  });

  it("fails and names a module the snapshot does not know", () => {
    repo = makeRepo();
    repo.write({
      [MODULES_API]: api(),
      ...manifest("recipes"),
      [SNAPSHOT]: [],
    });

    const { status, stderr } = run();

    expect(status).toBe(1);
    expect(stderr).toContain("MODULE-CATALOG ADDED   recipes");
    expect(stderr).toContain("check:modules:catalog:sync-backend");
  });

  it("fails and names a snapshot entry the backend no longer has", () => {
    repo = makeRepo();
    repo.write({
      [MODULES_API]: api(),
      ...manifest("recipes", { is_reference: true }),
      [SNAPSHOT]: ["recipes"],
    });

    const { status, stderr } = run();

    expect(status).toBe(1);
    expect(stderr).toContain("MODULE-CATALOG REMOVED recipes");
  });

  it("adds a virtual module the endpoint assembles by hand", () => {
    repo = makeRepo();
    repo.write({
      [MODULES_API]: api("core_tools"),
      ...manifest("recipes"),
      [SNAPSHOT]: ["recipes"],
    });

    const { status, stderr } = run();

    expect(status).toBe(1);
    expect(stderr).toContain("MODULE-CATALOG ADDED   core_tools");
  });

  it("errors, not an empty list, when the endpoint no longer has the virtual block", () => {
    repo = makeRepo();
    repo.write({
      [MODULES_API]: "def available():\n    return []\n",
      ...manifest("recipes"),
      [SNAPSHOT]: ["recipes"],
    });

    const { status, stderr } = run();

    expect(status).not.toBe(0);
    expect(stderr).toContain("no 'virtual_modules = [' in");
  });

  it("errors when the virtual block does not close where the gate expects", () => {
    repo = makeRepo();
    repo.write({
      [MODULES_API]: "virtual_modules = [ ModuleInfo(name='a') ]\n",
      ...manifest("recipes"),
      [SNAPSHOT]: ["recipes"],
    });

    const { status, stderr } = run();

    expect(status).not.toBe(0);
    expect(stderr).toContain("does not close");
  });

  it("reads the snapshot alone, and exits 0, when the backend is not mounted", () => {
    repo = makeRepo();
    repo.write({ [SNAPSHOT]: ["a", "b", "c"] });

    const { status, stdout } = run();

    expect(status).toBe(0);
    expect(stdout).toContain("3 module(s), snapshot only");
  });

  it("--sync-backend writes the sorted catalog and the next run is green", () => {
    repo = makeRepo();
    repo.write({
      [MODULES_API]: api("core_tools"),
      ...manifest("zeta"),
      ...manifest("alpha"),
      [SNAPSHOT]: [],
    });

    const sync = run(["--sync-backend"]);

    expect(sync.status).toBe(0);
    expect(sync.stdout).toContain("snapshot refreshed (3 modules)");
    expect(run().status).toBe(0);
  });

  it("--sync-backend refuses without the backend tree", () => {
    repo = makeRepo();

    const { status, stderr } = run(["--sync-backend"]);

    expect(status).toBe(1);
    expect(stderr).toContain("needs the backend tree");
  });
});
