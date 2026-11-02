import { describe, it, expect } from "vitest";

import {
  aliasTarget,
  baselineLines,
  declarations,
  diffBaseline,
  findingsIn,
  isScanned,
  rightHandSide,
  schemaNames,
} from "./check-api-types-mirror.mjs";

const GENERATED = `
export interface components {
    schemas: {
        /** Item */
        Item: {
            id: string;
            ByCategory: { n: number };
            nested: {
                child: string;
            };
        };
        /** WidgetDTO */
        WidgetDTO: {
            id: string;
        };
        /** DocumentLineStatus */
        DocumentLineStatus: "PENDING" | "DONE";
        "StockTakeCountRead-Input": {
            counted: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
}
export interface operations {
    list_items_api_items_get: {
        parameters: {
            query?: { q?: string };
        };
        requestBody: {
            content: { "application/json": { id: string } };
        };
        responses: {
            200: { content: { "application/json": unknown } };
        };
    };
}
`;
const SCHEMAS = schemaNames(GENERATED);

describe("check-api-types-mirror", () => {
  it("reads the schema block: objects, named unions and quoted keys", () => {
    expect([...SCHEMAS]).toEqual([
      "Item",
      "WidgetDTO",
      "DocumentLineStatus",
      "StockTakeCountRead-Input",
    ]);
  });

  it("does not watch an operation's parameters, requestBody or responses", () => {
    expect(SCHEMAS.has("parameters")).toBe(false);
    expect(SCHEMAS.has("requestBody")).toBe(false);
    expect(SCHEMAS.has("responses")).toBe(false);
  });

  it("catches a hand-written copy of a named union schema", () => {
    const source = `export type DocumentLineStatus = "BOGUS";\n`;
    const findings = findingsIn("src/types/x.ts", source, SCHEMAS);

    expect(findings).toHaveLength(1);
    expect(findings[0]).toMatchObject({
      path: "src/types/x.ts",
      name: "DocumentLineStatus",
      reason: "a hand-written type",
    });
  });

  it("lets a named union's alias through", () => {
    const source = `export type DocumentLineStatus = components["schemas"]["DocumentLineStatus"];\n`;
    expect(findingsIn("src/types/x.ts", source, SCHEMAS)).toEqual([]);
  });

  it("finds a hand-written interface sitting under a schema's name", () => {
    const source = `export interface Item {\n  id: string;\n}\n`;
    const findings = findingsIn("src/types/x.ts", source, SCHEMAS);

    expect(findings).toHaveLength(1);
    expect(findings[0]).toMatchObject({
      path: "src/types/x.ts",
      name: "Item",
      reason: "a hand-written interface",
    });
  });

  it("lets an alias through", () => {
    const source = `export type Item = components["schemas"]["Item"];\n`;
    expect(findingsIn("src/types/x.ts", source, SCHEMAS)).toEqual([]);
  });

  it("catches a copy that is a type rather than an interface", () => {
    const source = `export type Item = { id: string };\n`;
    const findings = findingsIn("src/types/x.ts", source, SCHEMAS);

    expect(findings).toHaveLength(1);
    expect(findings[0].reason).toBe("a hand-written type");
  });

  it("ignores a name no schema holds", () => {
    const source = `export interface ItemProps {\n  id: string;\n}\n`;
    expect(findingsIn("src/types/x.ts", source, SCHEMAS)).toEqual([]);
  });

  it("reads an alias's right-hand side past the braces it holds", () => {
    expect(rightHandSide(`export type A = { a: string }; rest`, 0)).toBe(
      " { a: string }",
    );
    expect(rightHandSide(`export type A = (f: () => void) => B;`, 0)).toBe(
      " (f: () => void) => B",
    );
    expect(rightHandSide(`export type A<T = X> = Y<T>;`, 0)).toBe(" Y<T>");
  });

  it("accepts only the bare reference as an alias", () => {
    expect(aliasTarget(`components["schemas"]["Item"]`)).toBe("Item");
    expect(aliasTarget(`components["schemas"]["Other"]`)).toBe("Other");
    expect(aliasTarget(`Pick<components["schemas"]["Item"], "id">`)).toBe(null);
    expect(aliasTarget(`components["schemas"]["Item"] | null`)).toBe(null);
    expect(aliasTarget(`{ id: string }`)).toBe(null);
  });

  it("names the schema a wrong alias points at", () => {
    const source = `export type Item = components["schemas"]["Other"];\n`;
    const findings = findingsIn("src/types/x.ts", source, SCHEMAS);

    expect(findings).toHaveLength(1);
    expect(findings[0].reason).toBe('an alias of "Other", not of "Item"');
  });

  it("reads a declaration's kind and name", () => {
    expect(
      declarations(`export type A = string;\nexport interface B {\n}\n`),
    ).toEqual([
      { kind: "type", name: "A", index: 0, line: 1 },
      { kind: "interface", name: "B", index: 24, line: 2 },
    ]);
  });

  it("flags a non-exported copy under a schema's name", () => {
    const schemas = new Set(["Item"]);
    const findings = findingsIn("x.ts", `interface Item {\n  id: string;\n}\n`, schemas);
    expect(findings.map((f) => f.name)).toEqual(["Item"]);
    expect(findingsIn("x.ts", `type Item = components["schemas"]["Item"];\n`, schemas)).toEqual([]);
  });

  it("finds an interface that shadows a suffixed schema under its bare name", () => {
    const findings = findingsIn(
      "src/x.ts",
      `export interface Widget {\n  id: string;\n}\n`,
      SCHEMAS,
    );

    expect(findings).toHaveLength(1);
    expect(findings[0]).toMatchObject({ name: "Widget" });
    expect(findings[0].reason).toContain("under a schema's name");
  });

  it("finds a hand-written object type that shadows a suffixed schema", () => {
    const findings = findingsIn("src/x.ts", `export type Widget = { id: string };\n`, SCHEMAS);
    expect(findings.map((f) => f.name)).toEqual(["Widget"]);
  });

  it("lets a shadowing name through as an alias, a derived type or a @mirrors interface", () => {
    const alias = `export type Widget = components["schemas"]["WidgetDTO"];\n`;
    const derived = `export type Widget = Omit<components["schemas"]["WidgetDTO"], "id"> & { x: 1 };\n`;
    const mirrored =
      `/**\n * @mirrors components["schemas"]["WidgetDTO"]\n */\nexport interface Widget {\n  id: string;\n}\n`;
    const object = `export type Widget = components["schemas"]["WidgetDTO"] & { x: 1 };\n`;
    for (const source of [alias, derived, mirrored, object]) {
      expect(findingsIn("src/x.ts", source, SCHEMAS)).toEqual([]);
    }
  });

  it("finds a type that only looks derived: parenthesised, unrelated or merely mentioning a schema", () => {
    const sources = [
      `export type Widget = ({ id: number });\n`,
      `export type Widget = Record<string, number>;\n`,
      `export type Widget = { unrelated: components["schemas"]["WidgetDTO"]; id: number };\n`,
      `export type Widget = { id: number } & { other: components["schemas"]["WidgetDTO"] };\n`,
      `export type Widget = (typeof WIDGET_KINDS)[number];\n`,
      `export type Widget = Array<{ id: number; x: components["schemas"]["WidgetDTO"] }>;\n`,
      `export type Widget = components["schemas"]["Item"] & { id: number; name: string };\n`,
      `export type Widget = { id: number } & Array<components["schemas"]["Item"]>;\n`,
    ];
    for (const source of sources) {
      expect(findingsIn("src/x.ts", source, SCHEMAS).map((f) => f.name), source).toEqual(["Widget"]);
    }
  });

  it("lets a parenthesised or union derivation through", () => {
    const sources = [
      `export type Widget = (components["schemas"]["WidgetDTO"]);\n`,
      `export type Widget = { x: 1 } & Omit<components["schemas"]["WidgetDTO"], "id">;\n`,
      `export type Widget = (Pick<components["schemas"]["WidgetDTO"], "id"> | null);\n`,
      `export type Widget = Schemas["WidgetDTO"];\n`,
      `export type Widget = components["schemas"]["Item"];\n`,
    ];
    for (const source of sources) {
      expect(findingsIn("src/x.ts", source, SCHEMAS), source).toEqual([]);
    }
  });

  it("does not accept a @mirrors of a different schema, or a stale comment further up", () => {
    const other = `/** @mirrors components["schemas"]["Item"] */\nexport interface Widget {\n}\n`;
    expect(findingsIn("src/x.ts", other, SCHEMAS)).toHaveLength(1);
    const stale = `/** @mirrors components["schemas"]["WidgetDTO"] */\nexport interface Other {\n}\nexport interface Widget {\n}\n`;
    expect(findingsIn("src/x.ts", stale, SCHEMAS)).toHaveLength(1);
  });

  it("leaves tests and the generated file out of the scan", () => {
    expect(isScanned("types/api-generated.ts")).toBe(false);
    expect(isScanned("modules/x/x.test.ts")).toBe(false);
    expect(isScanned("modules/x/x.spec.tsx")).toBe(false);
    expect(isScanned("modules/x/types.ts")).toBe(true);
  });

  it("writes the baseline sorted by path, then by name, once per key", () => {
    const findings = [
      { path: "src/b.ts", name: "Zeta" },
      { path: "src/a.ts", name: "Beta" },
      { path: "src/a.ts", name: "Alpha" },
      { path: "src/a.ts", name: "Alpha" },
    ];
    expect(baselineLines(findings)).toEqual([
      "src/a.ts::Alpha",
      "src/a.ts::Beta",
      "src/b.ts::Zeta",
    ]);
  });

  it("reports a key the baseline has never seen, and one it no longer needs", () => {
    const { added, fixed } = diffBaseline(
      ["src/a.ts::Alpha"],
      ["src/a.ts::Alpha", "src/a.ts::Gone"],
    );

    expect(added).toEqual([]);
    expect(fixed).toEqual(["src/a.ts::Gone"]);
    expect(diffBaseline(["src/a.ts::New"], ["src/a.ts::Alpha"]).added).toEqual([
      "src/a.ts::New",
    ]);
  });
});
