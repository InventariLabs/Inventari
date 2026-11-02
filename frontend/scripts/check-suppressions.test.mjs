/**
 * The register only works if it cannot be satisfied by a half-filled entry —
 * an owner with no date, or a date long past, is the state this gate exists to
 * end.
 */
import { describe, expect, it } from "vitest";

import {
  auditRegister,
  collectSuppressions,
  stripJsonc,
} from "./check-suppressions.mjs";

const TODAY = new Date("2026-08-23");
const complete = {
  owner: "maintainers",
  expires: "2026-12-31",
  reason: "Waiting on a decision.",
};

describe("stripJsonc", () => {
  it("drops a trailing comment but keeps a slash inside a string", () => {
    const text = '{\n  "ignore": ["src/a.ts"] // why\n}';
    expect(JSON.parse(stripJsonc(text)).ignore).toEqual(["src/a.ts"]);
  });

  it("drops a whole-line comment and tolerates the trailing comma it leaves", () => {
    const text = '{\n  "ignore": [\n    // why\n    "src/a.ts",\n  ]\n}';
    expect(JSON.parse(stripJsonc(text)).ignore).toEqual(["src/a.ts"]);
  });
});

describe("collectSuppressions", () => {
  const sources = [
    {
      name: "knip.json:ignore",
      file: "knip.json",
      read: (d) => d.ignore ?? [],
    },
    { name: "baseline", file: "b.json", read: (d) => d.unreachable ?? [] },
  ];

  it("keys each entry by source and value", () => {
    const load = (f) =>
      f === "knip.json" ? { ignore: ["src/a.ts"] } : { unreachable: ["b.ts"] };
    expect(collectSuppressions(sources, load).map((s) => s.id)).toEqual([
      "knip.json:ignore::src/a.ts",
      "baseline::b.ts",
    ]);
  });

  it("skips a source file that does not exist", () => {
    expect(collectSuppressions(sources, () => null)).toEqual([]);
  });
});

describe("auditRegister", () => {
  const suppression = [
    { id: "baseline::a.ts", source: "baseline", entry: "a.ts" },
  ];

  it("accepts a complete record", () => {
    const register = { suppressions: { "baseline::a.ts": complete } };
    expect(auditRegister(suppression, register, TODAY)).toEqual({
      errors: [],
      stale: [],
    });
  });

  it("refuses a suppression with no record at all", () => {
    const { errors } = auditRegister(suppression, { suppressions: {} }, TODAY);
    expect(errors).toHaveLength(1);
    expect(errors[0]).toContain("no record in suppressions.json");
  });

  it("refuses a record missing an owner, a reason or a date", () => {
    const missing = (over) =>
      auditRegister(
        suppression,
        { suppressions: { "baseline::a.ts": { ...complete, ...over } } },
        TODAY,
      ).errors;
    expect(missing({ owner: undefined })[0]).toContain("names nobody");
    expect(missing({ reason: undefined })[0]).toContain("gives no reason");
    expect(missing({ expires: undefined })[0]).toContain("YYYY-MM-DD");
  });

  it("refuses a record past its date and names who owed the answer", () => {
    const { errors } = auditRegister(
      suppression,
      {
        suppressions: {
          "baseline::a.ts": { ...complete, expires: "2026-01-01" },
        },
      },
      TODAY,
    );
    expect(errors[0]).toContain("expired on 2026-01-01");
    expect(errors[0]).toContain("maintainers");
  });

  it("reports a record that no longer silences anything, without failing", () => {
    const { errors, stale } = auditRegister(
      [],
      { suppressions: { "baseline::gone.ts": complete } },
      TODAY,
    );
    expect(errors).toEqual([]);
    expect(stale).toEqual(["baseline::gone.ts"]);
  });
});
