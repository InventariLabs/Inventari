/**
 * The gate is code that fails silently: when it stops recognising an import
 * shape, every file imported that way turns "reachable" and nothing reports
 * it. These cases pin the shapes that decide the verdict — the `@/` alias,
 * re-exports, dynamic `import()` — and the distinction the gate exists for:
 * a file whose only importer is its own spec is not ordinary dead code.
 */
import { describe, expect, it } from "vitest";

import {
  resolveSpecifier,
  specifiersOf,
  unreachableFrom,
} from "./check-reachability.mjs";

describe("specifiersOf", () => {
  it("reads default, named and side-effect imports", () => {
    expect(specifiersOf('import App from "@/App";')).toContain("@/App");
    expect(specifiersOf('import { a, b } from "./x";')).toContain("./x");
    expect(specifiersOf('import "@/index.css";')).toContain("@/index.css");
  });

  it("reads a re-export — a barrel keeps the file alive just as well", () => {
    expect(specifiersOf('export { Widget } from "./Widget";')).toContain(
      "./Widget",
    );
    expect(specifiersOf('export * from "@/lib/utils";')).toContain(
      "@/lib/utils",
    );
  });

  it("reads a lazy route's dynamic import", () => {
    expect(
      specifiersOf('const P = lazy(() => import("@/pages/P"));'),
    ).toContain("@/pages/P");
  });

  it("reads a multi-line import — prettier wraps long member lists", () => {
    expect(
      specifiersOf('import {\n  a,\n  b,\n} from "@/modules/x/hooks/useX";'),
    ).toContain("@/modules/x/hooks/useX");
  });

  it("ignores the word import inside a string or identifier", () => {
    expect(specifiersOf('const importPath = "./nope";').size).toBe(0);
  });
});

describe("resolveSpecifier", () => {
  const known = new Set([
    "components/ui/Button.tsx",
    "modules/x/index.ts",
    "lib/utils.ts",
  ]);

  it("resolves the @/ alias and a relative hop", () => {
    expect(resolveSpecifier("@/lib/utils", "App.tsx", known)).toBe(
      "lib/utils.ts",
    );
    expect(
      resolveSpecifier("../../../lib/utils", "modules/x/hooks/useX.ts", known),
    ).toBe("lib/utils.ts");
  });

  it("resolves a directory to its index", () => {
    expect(resolveSpecifier("@/modules/x", "App.tsx", known)).toBe(
      "modules/x/index.ts",
    );
  });

  it("returns null for a package and for anything outside src/", () => {
    expect(resolveSpecifier("react", "App.tsx", known)).toBeNull();
    expect(resolveSpecifier("../../vite.config", "App.tsx", known)).toBeNull();
  });
});

describe("unreachableFrom", () => {
  const graph = (files) => unreachableFrom(Object.keys(files), (f) => files[f]);

  it("reaches a component through App.tsx", () => {
    const { findings } = graph({
      "App.tsx": 'import { Panel } from "@/modules/x/Panel";',
      "modules/x/Panel.tsx": "export const Panel = () => null;",
    });
    expect(findings).toEqual([]);
  });

  it("reaches a component through its module registration", () => {
    const { findings } = graph({
      "App.tsx": "",
      "modules/x/module.ts": 'import "./Page";',
      "modules/x/Page.tsx": "export const Page = () => null;",
    });
    expect(findings).toEqual([]);
  });

  it("flags a file whose only importer is its own spec", () => {
    const { findings } = graph({
      "App.tsx": "",
      "modules/x/Orphan.tsx": "export const Orphan = () => null;",
      "modules/x/Orphan.test.tsx": 'import { Orphan } from "./Orphan";',
    });
    expect(findings).toEqual([
      { file: "modules/x/Orphan.tsx", testOnly: true, importers: 1 },
    ]);
  });

  it("flags a cluster no root reaches, however well it imports itself", () => {
    const { findings } = graph({
      "App.tsx": "",
      "modules/x/Sheet.tsx": 'import { row } from "./row";',
      "modules/x/row.ts": "export const row = 1;",
    });
    expect(findings.map((f) => f.file)).toEqual([
      "modules/x/Sheet.tsx",
      "modules/x/row.ts",
    ]);
    expect(findings.every((f) => f.testOnly)).toBe(false);
  });

  it("never reports a spec, a mock or the generated route table", () => {
    const { findings } = graph({
      "App.tsx": "",
      "modules/x/Orphan.test.tsx": "",
      "test/setup.ts": "",
      "modules/x/__mocks__/api.ts": "",
      "types/api-routes.ts": "export const ROUTES = {};",
    });
    expect(findings).toEqual([]);
  });
});
