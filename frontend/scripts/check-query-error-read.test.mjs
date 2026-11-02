import { describe, expect, it } from "vitest";

import { diffBaseline, unreadErrorsIn } from "./check-query-error-read.mjs";

/**
 * The gate flags a defaulted query result whose error the same destructuring
 * never takes. These cases pin both directions: the shapes that must fire,
 * and the ones that must not, so the baseline stays a list of real gaps.
 */

const rel = "modules/things/pages/ThingsPage.tsx";

describe("check-query-error-read", () => {
  it("fires on a data default with no error read", () => {
    expect(
      unreadErrorsIn(rel, "const { data: things = [] } = useThings();"),
    ).toMatchObject([{ file: rel, line: 1 }]);
  });

  it("fires on a default applied at the use", () => {
    const source = [
      "const { data: page } = useThings();",
      "const total = page?.total ?? 0;",
    ].join("\n");
    expect(unreadErrorsIn(rel, source)).toMatchObject([{ file: rel, line: 1 }]);
  });

  it("fires on a whole-query variable read through .data", () => {
    const source = [
      "const q = useThings();",
      "const rows = q.data ?? [];",
    ].join("\n");
    expect(unreadErrorsIn(rel, source)).toMatchObject([{ file: rel, line: 1 }]);
  });

  it("does not fire when the destructuring takes isError or error", () => {
    const source = [
      "const { data: a = [], isError } = useThings();",
      "const { data: b = [], error: loadError } = useOthers();",
      "if (isError || loadError) return null;",
    ].join("\n");
    expect(unreadErrorsIn(rel, source)).toEqual([]);
  });

  it("fires when isError is taken but never read", () => {
    const source = [
      "const { data = [], isError } = useThings();",
      "const n = data.length;",
    ].join("\n");
    expect(unreadErrorsIn(rel, source)).toHaveLength(1);
  });

  it("does not fire without an empty default", () => {
    expect(unreadErrorsIn(rel, "const { data } = useThings();")).toEqual([]);
  });

  it("does not fire when the whole-query variable reads isError", () => {
    const source = [
      "const q = useThings();",
      "const rows = q.data ?? [];",
      "if (q.isError) return null;",
    ].join("\n");
    expect(unreadErrorsIn(rel, source)).toEqual([]);
  });

  it("ignores a destructuring that is not a hook call", () => {
    expect(unreadErrorsIn(rel, "const { data = [] } = props;")).toEqual([]);
  });

  it("fails only on sites the baseline does not hold", () => {
    const findings = [{ file: "a.tsx", line: 1, site: "useA { data = [] }" }];
    const key = "a.tsx :: useA { data = [] }";
    expect(diffBaseline(findings, { [key]: 1 }).added).toEqual([]);
    expect(diffBaseline(findings, {}).added).toEqual([
      { key, was: 0, now: 1 },
    ]);
  });

  it("does not let a new site in a file inherit a fixed one's allowance", () => {
    const swapped = [{ file: "a.tsx", line: 9, site: "useB { data = [] }" }];
    const old = { "a.tsx :: useA { data = [] }": 1 };
    expect(diffBaseline(swapped, old).added).toHaveLength(1);
  });

  it("does not take another component's read for this query's", () => {
    const source = [
      "function Good() {",
      "  const { data = [], isError } = useThings();",
      "  if (isError) return null;",
      "  return data.length;",
      "}",
      "function Bad() {",
      "  const { data = [], isError } = useThings();",
      '  return { title: "isError", count: data.length };',
      "}",
    ].join("\n");
    expect(unreadErrorsIn(rel, source)).toMatchObject([
      { line: 7, site: expect.stringContaining("Bad ::") },
    ]);
  });

  it("names the enclosing declaration, so a replacement is a new site", () => {
    const at = (name) =>
      unreadErrorsIn(rel, `function ${name}() {\n  const { data = [] } = useThings();\n}`);
    const old = Object.fromEntries(
      [...new Set(at("Old").map((f) => `${f.file} :: ${f.site}`))].map((k) => [k, 1]),
    );
    expect(diffBaseline(at("Old"), old).added).toEqual([]);
    expect(diffBaseline(at("New"), old).added).toHaveLength(1);
  });

  it("does not take another query's isError, or template text, for a read", () => {
    const other = [
      "function C() {",
      "  const { data = [], isError } = useA();",
      "  const other = useB();",
      "  if (other.isError) return null;",
      "  return data.length;",
      "}",
    ].join("\n");
    expect(unreadErrorsIn(rel, other)).toHaveLength(1);
    const template = [
      "function C() {",
      "  const { data = [], isError } = useA();",
      "  const label = `isError`;",
      "  return data.length;",
      "}",
    ].join("\n");
    expect(unreadErrorsIn(rel, template)).toHaveLength(1);
    const hole = template.replace("`isError`", "`${isError}`");
    expect(unreadErrorsIn(rel, hole)).toHaveLength(0);
  });

  it("fires on an inline query read that binds no error at all", () => {
    expect(
      unreadErrorsIn(rel, "const scopes = useThings().data?.scopes ?? [];"),
    ).toMatchObject([{ line: 1, site: "<module> :: useThings().data" }]);
    expect(
      unreadErrorsIn(rel, "const has = (useThings({ a: f(1) }).data ?? []).length;"),
    ).toHaveLength(1);
    expect(unreadErrorsIn(rel, "const n = useThings().data?.total;")).toEqual(
      [],
    );
  });

  it("does not let a plain destructuring hide a read of the error", () => {
    const source = [
      "function C(props) {",
      "  const { data = [], isError } = useA();",
      "  const { id } = props;",
      '  const label = isError ? "failed" : id;',
      "  const { data: other } = useB();",
      "  return data.length + label + other;",
      "}",
    ].join("\n");
    expect(unreadErrorsIn(rel, source)).toEqual([]);
  });

  it("does not take another declaration's fallback for this query's", () => {
    const source = [
      "function Good() { const { data } = useA(); return data?.name; }",
      "function Bad() { const { data } = useB(); return data ?? []; }",
    ].join("\n");
    expect(unreadErrorsIn(rel, source)).toMatchObject([
      { line: 2, site: "Bad :: useB data" },
    ]);
  });
});
