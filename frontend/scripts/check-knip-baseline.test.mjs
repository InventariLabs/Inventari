/**
 * The dead-code baseline gate: fails on a finding the baseline does not know,
 * stays quiet about one it does, and refreshes the baseline only when asked.
 * knip itself is replaced by a stub that prints a fixed report, so the specs
 * pin how the gate reads and flattens a report, not what knip finds.
 */
import { afterEach, describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { makeRepo, runGate } from "./gate-fixture.mjs";

const BASELINE = "frontend/scripts/knip-baseline.json";
const REPORT = {
  files: ["src/dead.ts"],
  issues: [
    {
      file: "src/a.ts",
      dependencies: [{ name: "left-pad" }],
      devDependencies: [{ name: "vitest-x" }],
      unlisted: [{ name: "ghost" }],
      exports: [{ name: "unused" }],
      types: [{ name: "Unused" }],
    },
  ],
};
const KEYS = [
  "dependencies:left-pad",
  "devDependencies:vitest-x",
  "exports:src/a.ts:unused",
  "files:src/dead.ts",
  "types:src/a.ts:Unused",
  "unlisted:ghost",
];

let repo;
afterEach(() => repo?.cleanup());

const fakeKnip = (output, exitCode) =>
  `process.stdout.write(${JSON.stringify(output)});\nprocess.exitCode = ${exitCode};\n`;

const run = ({
  baseline,
  knipOutput = JSON.stringify(REPORT),
  knipExit = 0,
  args = [],
}) => {
  repo = makeRepo();
  repo.write({
    "frontend/node_modules/knip/bin/knip.js": fakeKnip(knipOutput, knipExit),
    ...(baseline ? { [BASELINE]: { issues: baseline } } : {}),
  });
  return runGate(repo, "check-knip-baseline.mjs", { args });
};

describe("check-knip-baseline", () => {
  it("passes when every finding is already in the baseline", () => {
    const { status, stdout } = run({ baseline: KEYS });

    expect(status).toBe(0);
    expect(stdout).toContain("knip passed baseline: 6 known finding(s).");
  });

  it("fails on a finding the baseline does not know, and says not to grandfather it", () => {
    const { status, stderr } = run({ baseline: KEYS.slice(1) });

    expect(status).toBe(1);
    expect(stderr).toContain("NEW finding(s) (1)");
    expect(stderr).toContain("  - dependencies:left-pad");
    expect(stderr).toContain("do NOT grandfather");
  });

  it("treats a missing baseline as empty, so the first run reports everything", () => {
    const { status, stderr } = run({});

    expect(status).toBe(1);
    expect(stderr).toContain("NEW finding(s) (6)");
  });

  it("passes and says how many were fixed when the baseline holds more than is found", () => {
    const { status, stdout } = run({
      baseline: [...KEYS, "files:src/gone.ts"],
    });

    expect(status).toBe(0);
    expect(stdout).toContain("1 fixed/removed since baseline");
    expect(stdout).toContain("--write-baseline");
  });

  it("--write-baseline snapshots the flattened, sorted keys", () => {
    const { status, stdout } = run({ args: ["--write-baseline"] });

    expect(status).toBe(0);
    expect(stdout).toContain("knip baseline written: 6 finding(s)");
    expect(JSON.parse(readFileSync(join(repo.root, BASELINE), "utf8"))).toEqual(
      {
        issues: KEYS,
      },
    );
  });

  it("--full lists every finding and exits 0 even with an empty baseline", () => {
    const { status, stdout } = run({ args: ["--full"] });

    expect(status).toBe(0);
    expect(stdout).toContain("knip: 6 finding(s) (full report, non-blocking)");
    expect(stdout).toContain("  - files:src/dead.ts");
  });

  it("tolerates a report with nothing in it", () => {
    const { status, stdout } = run({ baseline: [], knipOutput: "{}" });

    expect(status).toBe(0);
    expect(stdout).toContain("0 known finding(s)");
  });

  it("stops with knip's own output when it printed no JSON, rather than passing", () => {
    const { status, stderr } = run({
      baseline: KEYS,
      knipOutput: "Error: cannot load knip.json",
      knipExit: 2,
    });

    expect(status).toBe(2);
    expect(stderr).toContain("cannot load knip.json");
    expect(stderr).toContain("knip exited with status 2");
  });

  it("fails, rather than passing, when knip printed no JSON yet exited 0", () => {
    const { status, stderr } = run({
      baseline: KEYS,
      knipOutput: "Deprecation notice: reporter flag has moved",
      knipExit: 0,
    });

    expect(status).toBe(1);
    expect(stderr).toContain("Deprecation notice");
    expect(stderr).toContain("knip exited with status 0");
  });
});
