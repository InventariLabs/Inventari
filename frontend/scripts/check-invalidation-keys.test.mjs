import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, it, expect } from "vitest";

import {
  invalidationKeyReport,
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
      verdict: "to-fold",
      owner: "jerzy",
      expiry: "2999-01-01",
    };
    const key = { file: "src/x.ts", line: 1, root: "a" };
    /** The day after a date, so a test never writes one the clock overtakes. */
    const dayAfter = (iso) => {
      const at = new Date(`${iso}T00:00:00Z`);
      at.setUTCDate(at.getUTCDate() + 1);
      return at.toISOString().slice(0, 10);
    };
    const run = (over) =>
      invalidationKeyReport({
        literals: [],
        foreign: [],
        phantoms: [],
        baseline: { exceptions: [] },
        today: "2026-10-08",
        ...over,
      });
    const audit = (over) =>
      run({
        foreign: [key],
        baseline: { exceptions: [{ ...entry, ...over }] },
      });

    it("fails a literal and a phantom root", () => {
      const { errors } = run({
        literals: ['src/a.ts:3 ["valuation", …]'],
        phantoms: ['src/a.ts:3 ["valuation", …]'],
      });

      expect(errors).toHaveLength(2);
      expect(errors.join("\n")).toContain("valuation");
    });

    it("fails a foreign key in a file the baseline does not list", () => {
      const { errors } = run({
        foreign: [{ file: "src/y.ts", line: 4, root: "ghost" }],
        baseline: { exceptions: [entry] },
      });

      expect(errors[0]).toContain("src/y.ts:4 (ghost)");
    });

    it("fails when a listed file's count is raised by hand-free growth", () => {
      const { errors } = run({
        foreign: [
          { file: "src/x.ts", line: 1, root: "a" },
          { file: "src/x.ts", line: 2, root: "b" },
        ],
        baseline: { exceptions: [entry] },
      });

      expect(errors[0]).toContain("baseline 1");
    });

    it("stays quiet while the count sits at the baseline", () => {
      expect(audit({})).toEqual({ errors: [], warnings: [] });
    });

    it("fails freed headroom: a count above the actual number", () => {
      const { errors } = audit({ count: 3 });

      expect(errors).toHaveLength(1);
      expect(errors[0]).toContain("baseline 3");
    });

    it("fails an entry whose file has no foreign key left", () => {
      const { errors } = run({ baseline: { exceptions: [entry] } });

      expect(errors.join("\n")).toContain("no longer matches");
    });

    it("refuses an entry with no reason, no owner or no known verdict", () => {
      const first = (over) => audit(over).errors[0];

      expect(first({ reason: "" })).toContain("has no reason");
      expect(first({ owner: "" })).toContain("has no owner");
      expect(first({ verdict: "" })).toContain("needs a verdict");
      expect(first({ verdict: "to-wire" })).toContain("needs a verdict");
    });

    it("accepts a by-design entry with no date and refuses one that carries a date", () => {
      const { expiry: _undated, ...byDesign } = {
        ...entry,
        verdict: "by-design",
      };

      expect(
        run({ foreign: [key], baseline: { exceptions: [byDesign] } }),
      ).toEqual({ errors: [], warnings: [] });
      expect(audit({ verdict: "by-design" }).errors[0]).toContain(
        "carries no date",
      );
    });

    it("refuses a to-fold entry with no date, or with one that is not a date", () => {
      expect(audit({ expiry: "" }).errors[0]).toContain("YYYY-MM-DD");
      expect(audit({ expiry: "soon" }).errors[0]).toContain("YYYY-MM-DD");
      expect(audit({ expiry: "2999-1-1" }).errors[0]).toContain("YYYY-MM-DD");
    });

    it("warns on a to-fold entry past its date, names who owed it, and refuses nothing", () => {
      const { errors, warnings } = audit({ expiry: "1999-01-01" });

      expect(errors).toEqual([]);
      expect(warnings).toHaveLength(1);
      expect(warnings[0]).toContain("expired on 1999-01-01");
      expect(warnings[0]).toContain("jerzy");
    });

    it("warns the day after the date it carries", () => {
      const { errors, warnings } = run({
        foreign: [key],
        baseline: { exceptions: [entry] },
        today: dayAfter(entry.expiry),
      });

      expect(errors).toEqual([]);
      expect(warnings).toHaveLength(1);
    });
  });
});

describe("invalidation-keys-baseline.json as committed", () => {
  const register = JSON.parse(
    readFileSync(
      join(import.meta.dirname, "invalidation-keys-baseline.json"),
      "utf8",
    ),
  );
  const foreign = register.exceptions.flatMap((e) =>
    Array.from({ length: e.count }, (_, i) => ({
      file: e.file,
      line: i + 1,
      root: "foreign",
    })),
  );

  // On a clock past every date it carries a dated entry may only warn: the
  // register must not refuse the pre-push gate of whoever commits that day.
  it("refuses none of its entries on a day past every date it carries", () => {
    expect(
      invalidationKeyReport({
        literals: [],
        foreign,
        phantoms: [],
        baseline: register,
        today: "2099-12-31",
      }).errors,
    ).toEqual([]);
  });
});
