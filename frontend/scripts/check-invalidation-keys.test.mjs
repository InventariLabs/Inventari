import { describe, it, expect } from "vitest";

import {
  invalidationKeyFailures,
  keyFindings,
  registeredRoots,
} from "./check-invalidation-keys.mjs";

const kinds = (source) =>
  keyFindings(source).map((f) => `${f.kind}:${f.root ?? ""}`);

describe("check-invalidation-keys", () => {
  it("reads the roots a key registry declares", () => {
    const source = `export const queryKeys = {
      items: { all: ["items"] as const },
      stats: { overview: ["stats", "overview"] as const },
    };`;

    expect(registeredRoots(source)).toEqual(new Set(["items", "stats"]));
  });

  describe("what counts as rooted at the registry", () => {
    it("accepts a property, a call, a spread and a derived const", () => {
      const source = `
        const detailKey = queryKeys.items.detail(id);
        useQuery({ queryKey: queryKeys.items.all });
        useQuery({ queryKey: [...queryKeys.items.all, "archived"] as const });
        qc.cancelQueries({ queryKey: detailKey });
        qc.invalidateQueries({ queryKey: queryKeys.maker.production(id) });
      `;

      expect(kinds(source).every((k) => k === "ok:")).toBe(true);
    });

    it("checks both branches of a conditional", () => {
      const source = `useQuery({ queryKey: id ? queryKeys.a.b(id) : ["a", "none"] });`;

      expect(kinds(source)).toEqual(["ok:", "literal:a"]);
    });
  });

  describe("planted phantoms", () => {
    it("catches a key passed through a variable", () => {
      const source = `
        const ghost = ["ghost"] as const;
        qc.invalidateQueries({ queryKey: ghost });
      `;

      expect(kinds(source)).toEqual(["foreign:ghost"]);
    });

    it("catches a spread and a concatenation of a foreign root", () => {
      const source = `
        qc.invalidateQueries({ queryKey: [...ghost, "x"] });
        qc.invalidateQueries({ queryKey: ghost.concat(["y"]) });
      `;

      expect(kinds(source)).toEqual(["foreign:ghost", "foreign:ghost"]);
    });

    it("catches a key handed to invalidateQueries as a whole filter", () => {
      expect(kinds(`qc.invalidateQueries(filters);`)).toEqual([
        "foreign:filters",
      ]);
      expect(kinds(`qc.invalidateQueries();`)).toEqual([]);
    });

    it("catches a key behind a local mini-registry and a shorthand", () => {
      const source = `
        const sabKeys = { all: ["sabotage-hidden-root"] as const };
        useQuery({ queryKey: sabKeys.all });
        useQuery({ queryKey });
      `;

      expect(kinds(source)).toEqual(["foreign:sabKeys", "foreign:queryKey"]);
    });

    it("does not trust a file-local queryKeys object as the registry", () => {
      const source = `
        const queryKeys = { ghost: ["shadow-ghost"] };
        useQuery({ queryKey: queryKeys.ghost });
      `;

      expect(kinds(source)).toEqual(["foreign:queryKeys"]);
    });

    it("sees a literal spread over several lines as an invalidation", () => {
      const source = `
        qc.invalidateQueries({
          queryKey: [
            "ghost",
            "deep",
          ],
        });
        useQuery({
          queryKey: ["read", "side"],
        });
      `;

      const found = keyFindings(source);
      expect(found.map((f) => [f.kind, f.root, f.invalidating])).toEqual([
        ["literal", "ghost", true],
        ["literal", "read", false],
      ]);
    });
  });

  describe("baseline", () => {
    const entry = {
      file: "src/x.ts",
      count: 1,
      reason: "local registry",
      owner: "jerzy",
      expiry: "2999-01-01",
    };
    const run = (over) =>
      invalidationKeyFailures({
        literals: [],
        foreign: [],
        phantoms: [],
        baseline: { exceptions: [] },
        today: "2026-10-08",
        ...over,
      });

    it("fails a literal and a phantom root", () => {
      const failures = run({
        literals: ['src/a.ts:3 ["valuation", …]'],
        phantoms: ['src/a.ts:3 ["valuation", …]'],
      });

      expect(failures).toHaveLength(2);
      expect(failures.join("\n")).toContain("valuation");
    });

    it("fails a foreign key in a file the baseline does not list", () => {
      const failures = run({
        foreign: [{ file: "src/y.ts", line: 4, root: "ghost" }],
        baseline: { exceptions: [entry] },
      });

      expect(failures[0]).toContain("src/y.ts:4 (ghost)");
    });

    it("fails when a listed file's count is raised by hand-free growth", () => {
      const failures = run({
        foreign: [
          { file: "src/x.ts", line: 1, root: "a" },
          { file: "src/x.ts", line: 2, root: "b" },
        ],
        baseline: { exceptions: [entry] },
      });

      expect(failures[0]).toContain("baseline 1");
    });

    it("stays quiet while the count sits at the baseline", () => {
      expect(
        run({
          foreign: [{ file: "src/x.ts", line: 1, root: "a" }],
          baseline: { exceptions: [entry] },
        }),
      ).toEqual([]);
    });

    it("fails freed headroom: a count above the actual number", () => {
      const failures = run({
        foreign: [{ file: "src/x.ts", line: 1, root: "a" }],
        baseline: { exceptions: [{ ...entry, count: 3 }] },
      });

      expect(failures).toHaveLength(1);
      expect(failures[0]).toContain("baseline 3");
    });

    it("fails an entry whose file has no foreign key left", () => {
      const failures = run({ baseline: { exceptions: [entry] } });

      expect(failures.join("\n")).toContain("no longer matches");
    });

    it("fails an entry with no reason or an expired one", () => {
      const failures = run({
        baseline: {
          exceptions: [
            { ...entry, reason: "" },
            { ...entry, file: "src/z.ts", expiry: "2026-01-01" },
          ],
        },
      });

      expect(failures.join("\n")).toContain("has no reason");
      expect(failures.join("\n")).toContain("expired on 2026-01-01");
    });
  });
});
