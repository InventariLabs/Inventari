/**
 * The settings snapshot gate: the frontend's list of modules that declare
 * settings must match the backend manifests wherever both trees are visible,
 * and must say so quietly where only the frontend is.
 */
import { afterEach, describe, expect, it } from "vitest";

import { makeRepo, runGate } from "./gate-fixture.mjs";

const SNAPSHOT = "frontend/scripts/module-settings.json";
const manifest = (name, hasSettings) => ({
  [`backend/app/modules/${name}/manifest.json`]: {
    name,
    has_settings_schema: hasSettings,
  },
});

let repo;
afterEach(() => repo?.cleanup());

const run = (args = []) => runGate(repo, "check-module-settings.mjs", { args });

describe("check-module-settings", () => {
  it("passes when the snapshot lists exactly the modules that declare settings", () => {
    repo = makeRepo();
    repo.write({
      ...manifest("recipes", true),
      ...manifest("labels", false),
      [SNAPSHOT]: ["recipes"],
    });

    const { status, stdout } = run();

    expect(status).toBe(0);
    expect(stdout).toContain("1 module(s) declare settings, snapshot matches");
  });

  it("fails and names a module that gained settings after the snapshot", () => {
    repo = makeRepo();
    repo.write({ ...manifest("recipes", true), [SNAPSHOT]: [] });

    const { status, stderr } = run();

    expect(status).toBe(1);
    expect(stderr).toContain("MODULE-SETTINGS ADDED   recipes");
    expect(stderr).toContain("check:modules:sync-backend");
  });

  it("fails and names a module the snapshot lists but no manifest declares", () => {
    repo = makeRepo();
    repo.write({ ...manifest("recipes", false), [SNAPSHOT]: ["recipes"] });

    const { status, stderr } = run();

    expect(status).toBe(1);
    expect(stderr).toContain("MODULE-SETTINGS REMOVED recipes");
  });

  it("only counts a manifest that says true, and skips a directory with none", () => {
    repo = makeRepo();
    repo.write({
      "backend/app/modules/nomanifest/readme.md": "x",
      "backend/app/modules/loose.txt": "x",
      ...manifest("labels", false),
      [SNAPSHOT]: [],
    });

    expect(run().status).toBe(0);
  });

  it("reads the snapshot alone, and exits 0, when the backend is not mounted", () => {
    repo = makeRepo();
    repo.write({ [SNAPSHOT]: ["recipes", "labels"] });

    const { status, stdout } = run();

    expect(status).toBe(0);
    expect(stdout).toContain("2 module(s), snapshot only");
  });

  it("--sync-backend rewrites the snapshot, sorted, and the next run is green", () => {
    repo = makeRepo();
    repo.write({
      ...manifest("zeta", true),
      ...manifest("alpha", true),
      [SNAPSHOT]: ["stale"],
    });

    const sync = run(["--sync-backend"]);

    expect(sync.status).toBe(0);
    expect(sync.stdout).toContain("snapshot refreshed (2 modules)");
    expect(run().status).toBe(0);
    expect(run().stdout).toContain("2 module(s) declare settings");
  });

  it("--sync-backend refuses without the backend tree rather than emptying the snapshot", () => {
    repo = makeRepo();
    repo.write({ [SNAPSHOT]: ["recipes"] });

    const { status, stderr } = run(["--sync-backend"]);

    expect(status).toBe(1);
    expect(stderr).toContain("needs the backend tree");
  });
});
