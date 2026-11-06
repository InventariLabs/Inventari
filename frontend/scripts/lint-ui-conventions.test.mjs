/**
 * The blocking UI convention gate. The detectors have specs of their own; what
 * is pinned here is the entry point's contract: it runs the BLOCKING subset
 * over `src/`, prints each failing rule with its sentence and its file:line,
 * and exits 1 only when something is found.
 */
import { afterEach, describe, expect, it } from "vitest";

import { BLOCKING } from "./ui-patterns/index.mjs";
import { makeRepo, runGate } from "./gate-fixture.mjs";

let repo;
afterEach(() => repo?.cleanup());

/** `border-weight` demoted from the blocking set, as a detector that only reports. */
const DEMOTE_BORDER_WEIGHT = {
  "ui-patterns/index.mjs": (text) =>
    `${text}\nBLOCKING.delete("border-weight");\n`,
};

const run = (files, options = {}) => {
  repo = makeRepo();
  repo.write(
    Object.fromEntries(
      Object.entries(files).map(([name, text]) => [
        `frontend/src/${name}`,
        text,
      ]),
    ),
  );
  return runGate(repo, "lint-ui-conventions.mjs", {
    siblings: ["ui-patterns"],
    ...options,
  });
};

describe("lint-ui-conventions", () => {
  it("passes a clean tree and reports every blocking rule it ran", () => {
    const { status, stdout } = run({
      "Clean.tsx":
        'export const A = () => <div className="rounded border" />;\n',
    });

    expect(status).toBe(0);
    expect(stdout).toContain("ui-conventions:");
    expect(stdout).toContain("0 violations");
    for (const name of BLOCKING) expect(stdout).toContain(`${name} `);
  });

  it("fails on a violation, printing the rule, its advice and the file:line", () => {
    const { status, stderr } = run({
      "Bad.tsx":
        'export const A = () => (\n  <div className="border-2 border-primary-500" />\n);\n',
    });

    expect(status).toBe(1);
    expect(stderr).toContain("border-weight:");
    expect(stderr).toContain("UI_GUIDELINES §2.10");
    expect(stderr).toContain("Emphasis is colour plus fill");
    expect(stderr).toContain("  src/Bad.tsx:2");
  });

  it("does not read a test file as source", () => {
    const { status } = run({
      "Bad.test.tsx": '<div className="border-2" />\n',
    });

    expect(status).toBe(0);
  });

  it("enforces only the blocking detectors, never the report-only ones", () => {
    const { status, stdout, stderr } = run(
      {
        "Bad.tsx":
          'export const A = () => <div className="border-2 border-primary-500" />;\n',
      },
      { patch: DEMOTE_BORDER_WEIGHT },
    );

    // The violation is real, but its detector no longer blocks: not run, not printed.
    expect(status).toBe(0);
    expect(stderr).toBe("");
    expect(stdout).toContain("0 violations");
    expect(stdout).not.toContain("border-weight ");
    expect(stdout).toContain("button-size-override ");
  });
});
