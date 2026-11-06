/**
 * The non-blocking UI pattern report: one count line per detector, tagged
 * [blocking] or [report], and always exit 0 — even when it finds something —
 * because its job is a number two reviews can compare, not a verdict.
 */
import { afterEach, describe, expect, it } from "vitest";

import { BLOCKING, DETECTORS } from "./ui-patterns/index.mjs";
import { makeRepo, runGate } from "./gate-fixture.mjs";

let repo;
afterEach(() => repo?.cleanup());

const run = (files, args = [], options = {}) => {
  repo = makeRepo();
  repo.write(
    Object.fromEntries(
      Object.entries(files).map(([name, text]) => [
        `frontend/src/${name}`,
        text,
      ]),
    ),
  );
  return runGate(repo, "scan-ui-patterns.mjs", {
    args,
    siblings: ["ui-patterns"],
    ...options,
  });
};

const BAD = {
  "Bad.tsx":
    'export const A = () => (\n  <div className="border-2 border-primary-500" />\n);\n',
  "hook.ts": "export const x = (error: Error) => error.message;\n",
  "Bad.test.tsx": "// ignored\n",
};

describe("scan-ui-patterns", () => {
  it("prints a count line for every detector, tagged by whether it blocks", () => {
    const { status, stdout } = run(BAD);

    expect(status).toBe(0);
    for (const d of DETECTORS) {
      const line = stdout.split("\n").find((l) => l.startsWith(`${d.name} `));
      expect(line, d.name).toBeDefined();
      expect(line).toContain(BLOCKING.has(d.name) ? "[blocking]" : "[report]");
    }
  });

  it("tags a detector [report] once it is not in the blocking set, and still counts it", () => {
    const { status, stdout } = run(BAD, [], {
      patch: {
        "ui-patterns/index.mjs": (text) =>
          `${text}\nBLOCKING.delete("border-weight");\n`,
      },
    });
    const line = (name) =>
      stdout.split("\n").find((l) => l.startsWith(`${name} `));

    expect(status).toBe(0);
    expect(line("border-weight")).toContain("[report]");
    expect(line("border-weight")).toMatch(/1 finding\(s\)/);
    expect(line("button-size-override")).toContain("[blocking]");
  });

  it("reads a .ts file for the rules that read hooks, and finds in it", () => {
    const { stdout } = run(BAD, ["--list"]);

    expect(stdout).toContain("error-message-as-copy — 1 finding(s)");
    expect(stdout).toContain("  src/hook.ts:1");
  });

  it("counts the files it read: tsx for markup, tsx plus ts for the hook rules, no tests", () => {
    const { stdout } = run(BAD);

    expect(stdout).toContain("1 non-test .tsx files under src/");
    expect(stdout).toContain(
      "2 counting .ts for the rules that read hooks too",
    );
  });

  it("counts a finding without failing, and points at --list", () => {
    const { status, stdout } = run(BAD);

    expect(status).toBe(0);
    expect(stdout).toMatch(
      /border-weight\s+1 finding\(s\) in\s+1 candidate file\(s\)/,
    );
    expect(stdout).toContain("Run with --list");
    expect(stdout).not.toContain("src/Bad.tsx:2");
  });

  it("--list names each finding with its file:line and the sentence explaining it", () => {
    const { status, stdout } = run(BAD, ["--list"]);

    expect(status).toBe(0);
    expect(stdout).toContain("border-weight — 1 finding(s)");
    expect(stdout).toContain("`border-2` is off the scale");
    expect(stdout).toContain("  src/Bad.tsx:2");
    expect(stdout).not.toContain("Run with --list");
  });

  it("--list on a clean tree prints no per-finding section", () => {
    const { status, stdout } = run(
      { "Clean.tsx": "export const A = () => null;\n" },
      ["--list"],
    );

    expect(status).toBe(0);
    expect(stdout).not.toContain(" finding(s)\n  ");
    expect(stdout).not.toMatch(/ — \d+ finding\(s\)/);
  });
});
