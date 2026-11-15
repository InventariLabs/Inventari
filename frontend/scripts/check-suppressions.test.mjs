/**
 * The register only works if it cannot be satisfied by a half-filled entry: a
 * suppression with nobody's name or no reason on it is the state this gate
 * exists to end. A date is what an entry that waits for a fix carries, and a
 * passed one warns — it never refuses whoever happens to commit that day.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

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
  const audit = (record) =>
    auditRegister(
      suppression,
      { suppressions: { "baseline::a.ts": record } },
      TODAY,
    );

  it("accepts a complete record", () => {
    expect(audit(complete)).toEqual({ errors: [], warnings: [], stale: [] });
  });

  it("accepts a record with no date: an exception right by design", () => {
    const { expires: _undated, ...byDesign } = complete;
    expect(audit(byDesign)).toEqual({ errors: [], warnings: [], stale: [] });
  });

  it("refuses a suppression with no record at all", () => {
    const { errors } = auditRegister(suppression, { suppressions: {} }, TODAY);
    expect(errors).toHaveLength(1);
    expect(errors[0]).toContain("no record in suppressions.json");
  });

  it("refuses a record missing an owner or a reason, or a date that is not one", () => {
    const missing = (over) => audit({ ...complete, ...over }).errors;
    expect(missing({ owner: undefined })[0]).toContain("names nobody");
    expect(missing({ reason: undefined })[0]).toContain("gives no reason");
    expect(missing({ expires: "soon" })[0]).toContain("YYYY-MM-DD");
  });

  it("warns on a record past its date, names who owed the answer, and refuses nothing", () => {
    const { errors, warnings } = audit({ ...complete, expires: "2026-01-01" });
    expect(errors).toEqual([]);
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toContain("expired on 2026-01-01");
    expect(warnings[0]).toContain("maintainers");
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

describe("suppressions.json as committed", () => {
  const register = JSON.parse(
    readFileSync(join(import.meta.dirname, "suppressions.json"), "utf8"),
  );
  const live = Object.keys(register.suppressions).map((id) => {
    const [source, entry] = id.split("::");
    return { id, source, entry };
  });

  // Past every date it could carry: a passed date may only warn.
  it("refuses none of its records on any later day", () => {
    expect(
      auditRegister(live, register, new Date("2099-12-31")).errors,
    ).toEqual([]);
  });
});
