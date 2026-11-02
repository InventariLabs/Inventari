/**
 * The ratchet's judgement, without ESLint in the loop: what counts as growth,
 * what counts as a paid debt, and what counts as an entry that silences
 * nothing. The other half — ESLint reporting a real function under the
 * re-enabled limit — is ESLint's own job and is not exercised here.
 */
import { describe, expect, it } from "vitest";

import {
  COMPLEXITY,
  MAX_LINES,
  bareName,
  compareRule,
  parseViolations,
  sortSnapshot,
} from "./check-function-baseline.mjs";

describe("bareName", () => {
  it("unwraps the name ESLint quotes", () => {
    expect(bareName("Function 'StatsPage'")).toBe("StatsPage");
    expect(bareName("Method 'method'")).toBe("method");
    expect(bareName("Async function 'Later'")).toBe("Later");
  });

  it("keeps an anonymous function's kind as its name", () => {
    // ESLint reports no inferred name for an arrow assigned to a variable —
    // the kind is all there is, and duplicates of one kind are compared as a
    // multiset by compareRule.
    expect(bareName("Arrow function")).toBe("Arrow function");
    expect(bareName("Function")).toBe("Function");
  });
});

describe("parseViolations", () => {
  it("groups values per file and function, relative to the root", () => {
    const results = [
      {
        filePath: "/app/src/modules/stats/pages/StatsPage.tsx",
        messages: [
          {
            ruleId: "complexity",
            message:
              "Function 'StatsPage' has a complexity of 51. Maximum allowed is 25.",
          },
          {
            ruleId: "max-lines-per-function",
            message:
              "Function 'StatsPage' has too many lines (310). Maximum allowed is 300.",
          },
          { ruleId: "no-console", message: "Unexpected console statement." },
        ],
      },
    ];

    expect(parseViolations(results, COMPLEXITY, "/app")).toEqual({
      "src/modules/stats/pages/StatsPage.tsx": { StatsPage: [51] },
    });
    expect(parseViolations(results, MAX_LINES, "/app")).toEqual({
      "src/modules/stats/pages/StatsPage.tsx": { StatsPage: [310] },
    });
  });

  it("keeps every value of a repeated anonymous name", () => {
    const results = [
      {
        filePath: "/app/src/a.tsx",
        messages: [
          {
            ruleId: "complexity",
            message:
              "Arrow function has a complexity of 30. Maximum allowed is 25.",
          },
          {
            ruleId: "complexity",
            message:
              "Arrow function has a complexity of 32. Maximum allowed is 25.",
          },
        ],
      },
    ];

    expect(parseViolations(results, COMPLEXITY, "/app")).toEqual({
      "src/a.tsx": { "Arrow function": [30, 32] },
    });
  });
});

describe("compareRule", () => {
  it("accepts an unchanged snapshot", () => {
    const frozen = { "src/a.tsx": { Foo: [54] } };
    expect(compareRule("complexity", { "src/a.tsx": { Foo: [54] } }, frozen)).toEqual([]);
  });

  it("fails a frozen function that grew", () => {
    const errors = compareRule(
      "complexity",
      { "src/a.tsx": { Foo: [55] } },
      { "src/a.tsx": { Foo: [54] } },
    );
    expect(errors).toHaveLength(1);
    expect(errors[0]).toContain("src/a.tsx");
    expect(errors[0]).toContain("Foo");
    expect(errors[0]).toContain("grew from 54 to 55");
  });

  it("fails a debt paid without refreshing the baseline", () => {
    const errors = compareRule(
      "complexity",
      { "src/a.tsx": { Foo: [50] } },
      { "src/a.tsx": { Foo: [54] } },
    );
    expect(errors).toHaveLength(1);
    expect(errors[0]).toContain("dropped from 54 to 50");
  });

  it("fails a finding the baseline does not freeze", () => {
    const errors = compareRule(
      "complexity",
      { "src/a.tsx": { Bar: [30] } },
      { "src/a.tsx": { Foo: [54] } },
    );
    expect(errors).toHaveLength(2);
    expect(errors[0]).toContain("not in the baseline");
    expect(errors[1]).toContain("no longer stands");
  });

  it("fails a file the baseline knows nothing about", () => {
    const errors = compareRule("complexity", { "src/new.tsx": { Foo: [30] } }, {});
    expect(errors).toHaveLength(1);
    expect(errors[0]).toContain("not in the baseline");
  });

  it("fails a frozen file whose last entry is gone", () => {
    const errors = compareRule("complexity", {}, { "src/a.tsx": { Foo: [54] } });
    expect(errors).toHaveLength(1);
    expect(errors[0]).toContain("no longer stands");
  });

  it("matches duplicates of an anonymous name as a multiset", () => {
    const frozen = { "src/a.tsx": { "Arrow function": [30, 32] } };
    expect(
      compareRule("complexity", { "src/a.tsx": { "Arrow function": [32, 30] } }, frozen),
    ).toEqual([]);
  });

  it("fails one same-kind function that dropped while the other held", () => {
    const errors = compareRule(
      "complexity",
      { "src/a.tsx": { "Arrow function": [29, 32] } },
      { "src/a.tsx": { "Arrow function": [30, 32] } },
    );
    expect(errors).toHaveLength(1);
    expect(errors[0]).toContain("dropped from 30 to 29");
  });

  it("fails one extra occurrence of a frozen name", () => {
    const errors = compareRule(
      "complexity",
      { "src/a.tsx": { "Arrow function": [30, 30] } },
      { "src/a.tsx": { "Arrow function": [30] } },
    );
    expect(errors).toHaveLength(1);
    expect(errors[0]).toContain("one more");
  });
});

describe("sortSnapshot", () => {
  it("sorts files, names and values so the written baseline is stable", () => {
    expect(
      sortSnapshot({
        "src/b.tsx": { B: [40, 30] },
        "src/a.tsx": { Z: [35], A: [40] },
      }),
    ).toEqual({
      "src/a.tsx": { A: [40], Z: [35] },
      "src/b.tsx": { B: [30, 40] },
    });
  });
});
