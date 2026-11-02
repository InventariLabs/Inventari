/**
 * The ratchet's judgement, without ESLint in the loop: what counts as growth,
 * as a paid debt and as an entry that silences nothing. ESLint reporting a
 * real violation is the plugin's own job and is not exercised here.
 */
import { describe, expect, it } from "vitest";

import {
  compareSnapshots,
  parseViolations,
  sortSnapshot,
} from "./check-a11y-baseline.mjs";

describe("parseViolations", () => {
  it("counts jsx-a11y findings per file and rule, relative to the root", () => {
    const results = [
      {
        filePath: "/app/src/components/ui/Sheet.tsx",
        messages: [
          { ruleId: "jsx-a11y/no-autofocus" },
          { ruleId: "jsx-a11y/no-autofocus" },
          { ruleId: "jsx-a11y/alt-text" },
          { ruleId: "no-console" },
          { ruleId: null },
        ],
      },
      { filePath: "/app/src/clean.tsx", messages: [{ ruleId: "no-console" }] },
    ];

    expect(parseViolations(results, "/app")).toEqual({
      "src/components/ui/Sheet.tsx": {
        "jsx-a11y/no-autofocus": 2,
        "jsx-a11y/alt-text": 1,
      },
    });
  });
});

describe("compareSnapshots", () => {
  const frozen = { "src/a.tsx": { "jsx-a11y/alt-text": 2 } };

  it("passes when nothing moved", () => {
    expect(compareSnapshots(structuredClone(frozen), frozen)).toEqual([]);
  });

  it("refuses a finding in a file the baseline does not know", () => {
    const errors = compareSnapshots(
      { ...frozen, "src/b.tsx": { "jsx-a11y/alt-text": 1 } },
      frozen,
    );
    expect(errors).toHaveLength(1);
    expect(errors[0]).toContain("src/b.tsx → jsx-a11y/alt-text");
    expect(errors[0]).toContain("not in the baseline");
  });

  it("refuses a frozen finding that multiplied", () => {
    const errors = compareSnapshots(
      { "src/a.tsx": { "jsx-a11y/alt-text": 3 } },
      frozen,
    );
    expect(errors[0]).toContain("grew from 2 to 3");
  });

  it("refuses a new rule in a listed file", () => {
    const errors = compareSnapshots(
      { "src/a.tsx": { "jsx-a11y/alt-text": 2, "jsx-a11y/no-autofocus": 1 } },
      frozen,
    );
    expect(errors).toHaveLength(1);
    expect(errors[0]).toContain("jsx-a11y/no-autofocus");
  });

  it("asks to lock a paid debt", () => {
    const errors = compareSnapshots(
      { "src/a.tsx": { "jsx-a11y/alt-text": 1 } },
      frozen,
    );
    expect(errors[0]).toContain("debt paid");
  });

  it("refuses an entry that silences nothing", () => {
    const errors = compareSnapshots({}, frozen);
    expect(errors[0]).toContain("no longer stands");
  });
});

describe("sortSnapshot", () => {
  it("orders files and rules so two runs write the same bytes", () => {
    const sorted = sortSnapshot({
      "src/b.tsx": { "jsx-a11y/b": 1, "jsx-a11y/a": 2 },
      "src/a.tsx": { "jsx-a11y/z": 1 },
    });
    expect(Object.keys(sorted)).toEqual(["src/a.tsx", "src/b.tsx"]);
    expect(Object.keys(sorted["src/b.tsx"])).toEqual([
      "jsx-a11y/a",
      "jsx-a11y/b",
    ]);
  });
});
