import { describe, it, expect } from "vitest";
import {
  coreImports,
  coreImportsIn,
  crossings,
  edgesIn,
  isCountedFile,
  SHARED_LAYERS,
} from "./check-module-boundaries.mjs";

describe("check-module-boundaries", () => {
  const modules = new Set([
    "nutrition",
    "inventory",
    "spaces",
    "stats",
    "printing",
    "shared",
    "settings",
  ]);

  it("reports a module reaching into another module", () => {
    expect(
      crossings(
        "nutrition/components/NutritionScanner.tsx",
        'import { visionApi } from "@/modules/stats/api/stats";',
        modules,
      ),
    ).toEqual(["nutrition/components/NutritionScanner.tsx → stats"]);
  });

  it("counts a dynamic alias import as the edge it is", () => {
    expect(
      crossings(
        "inventory/module.ts",
        'const Page = lazy(() => import("@/modules/spaces/pages/X"));',
        modules,
      ),
    ).toEqual(["inventory/module.ts → spaces"]);
  });

  it("counts a dynamic relative import, resolved from the file's own depth", () => {
    expect(
      crossings(
        "inventory/module.ts",
        'const Page = lazy(() => import("../spaces/pages/StoragesPage"));',
        modules,
      ),
    ).toEqual(["inventory/module.ts → spaces"]);
    expect(
      crossings(
        "inventory/pages/List.tsx",
        'import("../../spaces/api/storages").then(load)',
        modules,
      ),
    ).toEqual(["inventory/pages/List.tsx → spaces"]);
    expect(
      crossings(
        "inventory/pages/deep/List.tsx",
        'import("../../../spaces/api/storages").then(load)',
        modules,
      ),
    ).toEqual(["inventory/pages/deep/List.tsx → spaces"]);
    // One `..` too few lands inside the owner — that hop is not an edge.
    expect(
      crossings(
        "inventory/pages/deep/List.tsx",
        'import("../spaces/api/storages").then(load)',
        modules,
      ),
    ).toEqual([]);
  });

  it("counts a backtick specifier with no substitution as the edge it is", () => {
    expect(
      crossings(
        "inventory/module.ts",
        "const Page = lazy(() => import(`@/modules/spaces/pages/X`));",
        modules,
      ),
    ).toEqual(["inventory/module.ts → spaces"]);
    expect(
      crossings(
        "inventory/module.ts",
        "const Page = lazy(() => import(`../spaces/pages/StoragesPage`));",
        modules,
      ),
    ).toEqual(["inventory/module.ts → spaces"]);
  });

  it("leaves a specifier with a substitution alone — its target is a runtime name", () => {
    // The substituted piece may be the module name itself, where nothing is
    // left to read…
    expect(
      crossings(
        "inventory/module.ts",
        "const Page = lazy(() => import(`@/modules/${name}/pages/X`));",
        modules,
      ),
    ).toEqual([]);
    expect(
      crossings(
        "inventory/module.ts",
        "const Page = lazy(() => import(`../${name}/pages/X`));",
        modules,
      ),
    ).toEqual([]);
    // …or a segment after a module name the gate could read; a specifier
    // read in part is still not a specifier.
    expect(
      crossings(
        "inventory/module.ts",
        "const Page = lazy(() => import(`@/modules/spaces/${page}`));",
        modules,
      ),
    ).toEqual([]);
    expect(
      crossings(
        "inventory/module.ts",
        "const Page = lazy(() => import(`../spaces/${page}`));",
        modules,
      ),
    ).toEqual([]);
  });

  it("counts a relative static import too", () => {
    expect(
      crossings(
        "inventory/components/X.tsx",
        'import { storagesApi } from "../../stats/api/stats";',
        modules,
      ),
    ).toEqual(["inventory/components/X.tsx → stats"]);
  });

  it("lets a module reach another through its published moduleApi file", () => {
    // The door the owner keeps stable is not an edge; the module's internals
    // beside it still are, and so is a name that merely starts the same way.
    expect(
      crossings(
        "printing/components/X.tsx",
        'import { statsApi } from "@/modules/stats/moduleApi";\n' +
          'const lazyDoor = () => import("@/modules/stats/moduleApi");',
        modules,
      ),
    ).toEqual([]);
    expect(
      crossings(
        "printing/components/X.tsx",
        'import { statsApi } from "../../stats/moduleApi";',
        modules,
      ),
    ).toEqual([]);
    expect(
      crossings(
        "printing/components/X.tsx",
        'import { a } from "@/modules/stats/moduleApi";\n' +
          'import { b } from "@/modules/stats/api/stats";',
        modules,
      ),
    ).toEqual(["printing/components/X.tsx → stats"]);
    expect(
      crossings(
        "printing/components/X.tsx",
        'import { a } from "@/modules/stats/moduleApiExtras";\n' +
          'import { b } from "@/modules/stats/moduleApi/internal";',
        modules,
      ),
    ).toEqual(["printing/components/X.tsx → stats"]);
  });

  it("does not blame a relative hop that leaves modules/ entirely", () => {
    expect(
      crossings(
        "inventory/pages/deep/X.tsx",
        'import { Button } from "../../../components/ui/Button";',
        modules,
      ),
    ).toEqual([]);
  });

  it("counts a relative hop when the caller passes no module set", () => {
    // The module set defaults to empty: without it the landing spot cannot
    // be verified, and the safe default for a control is to count the hop —
    // an edge dropped in silence is the failure this gate exists to prevent.
    expect(
      crossings("inventory/module.ts", 'import("../spaces/pages/X")'),
    ).toEqual(["inventory/module.ts → spaces"]);
  });

  it("says nothing about a module importing from itself", () => {
    expect(
      crossings(
        "nutrition/components/X.tsx",
        'import { useNutrition } from "@/modules/nutrition/hooks/useNutrition";',
        modules,
      ),
    ).toEqual([]);
    expect(
      crossings(
        "inventory/module.ts",
        'const Self = lazy(() => import("./pages/ArchivedItemsPage"));',
        modules,
      ),
    ).toEqual([]);
  });

  it("lets every module lean on the shared layers", () => {
    for (const layer of SHARED_LAYERS) {
      expect(
        crossings(
          "documents/X.tsx",
          `import { a } from "@/modules/${layer}/b";`,
          modules,
        ),
      ).toEqual([]);
      expect(
        crossings(
          "warehouse/components/Y.tsx",
          `import("../${layer}/b").then(load)`,
          modules,
        ),
      ).toEqual([]);
    }
  });

  it("counts each target once, however many times it is imported", () => {
    const text = [
      'import { a } from "@/modules/spaces/one";',
      'const b = lazy(() => import("@/modules/spaces/two"));',
    ].join("\n");
    expect(crossings("inventory/X.tsx", text, modules)).toEqual([
      "inventory/X.tsx → spaces",
    ]);
  });

  it("ignores specs — a fixture borrowed by a test is not architecture", () => {
    expect(isCountedFile("inventory/X.test.tsx")).toBe(false);
    expect(isCountedFile("inventory/__tests__/X.tsx")).toBe(false);
    expect(isCountedFile("inventory/X.tsx")).toBe(true);
    expect(isCountedFile("inventory/README.md")).toBe(false);
  });

  it("returns the edges sorted, so the baseline diff stays readable", () => {
    const files = ["b/X.tsx", "a/Y.tsx"];
    const read = (rel) =>
      rel === "b/X.tsx"
        ? 'import { q } from "@/modules/spaces/q";'
        : 'import { r } from "@/modules/warehouse/r";';
    expect(edgesIn(files, read)).toEqual([
      "a/Y.tsx → warehouse",
      "b/X.tsx → spaces",
    ]);
  });

  it("reports a core import outside the module SDK", () => {
    expect(
      coreImports(
        "inventory/pages/List.tsx",
        'import { Button } from "@/components/ui/Button";',
      ),
    ).toEqual(["inventory → @/components/ui/Button"]);
    expect(
      coreImports(
        "inventory/hooks/useItems.ts",
        'const mod = await import("@/lib/api/client");',
      ),
    ).toEqual(["inventory → @/lib/api/client"]);
  });

  it("lets a module declare its own slot, and only that, through the slot map", () => {
    const declaration =
      'declare module "@/lib/moduleRegistry/slotProps" {\n  interface SlotDataMap { my_slot: { id: string } }\n}\n';
    expect(coreImports("notes/slots.d.ts", declaration)).toEqual([]);
    // An import of the same file is still Core internals.
    expect(
      coreImports(
        "notes/slots.d.ts",
        declaration +
          'import type { DocumentMetaData } from "@/lib/moduleRegistry/slotProps";',
      ),
    ).toEqual(["notes → @/lib/moduleRegistry/slotProps"]);
  });

  it("reports a core import written as a relative path", () => {
    // A valid relative specifier lands on the same file the alias names, and
    // the gate records it as the same dependency.
    expect(
      coreImports(
        "example_widgets/module.ts",
        'export { api as reviewerProbeApi } from "../../lib/api/client";',
      ),
    ).toEqual(["example_widgets → @/lib/api/client"]);
    expect(
      coreImports(
        "example_widgets/module.ts",
        'const m = await import("../../components/ui/Button");',
      ),
    ).toEqual(["example_widgets → @/components/ui/Button"]);
    expect(
      coreImports(
        "inventory/pages/deep/X.tsx",
        'import { cn } from "../../../../lib/utils";',
      ),
    ).toEqual(["inventory → @/lib/utils"]);
  });

  it("reads a relative core import once however it is spelled", () => {
    const text = [
      'import { api } from "@/lib/api/client";',
      'import type { Item } from "../../../../types";',
      'export { api as again } from "../../../../lib/api/client.ts";',
      'export { api as indexed } from "../../../../lib/api/index";',
    ].join("\n");
    expect(coreImports("inventory/pages/deep/X.tsx", text)).toEqual([
      "inventory → @/lib/api",
      "inventory → @/lib/api/client",
      "inventory → @/types",
    ]);
  });

  it("leaves a relative hop inside the module or into another module to the other rule", () => {
    expect(
      coreImports(
        "inventory/pages/X.tsx",
        'import { useItems } from "../api/items";',
      ),
    ).toEqual([]);
    expect(
      coreImports(
        "inventory/module.ts",
        'import { storagesApi } from "../spaces/api/storages";',
      ),
    ).toEqual([]);
  });

  it("does not read a plain string that happens to start with a dot", () => {
    expect(
      coreImports(
        "inventory/pages/X.tsx",
        'const relative = "../../lib/api/client";',
      ),
    ).toEqual([]);
  });

  it("accepts the SDK itself and leaves module-to-module edges to the other rule", () => {
    expect(
      coreImports(
        "inventory/module.ts",
        [
          'import { moduleRegistry } from "@/module-sdk";',
          'import { storageApi } from "@/modules/spaces/api/storages";',
        ].join("\n"),
      ),
    ).toEqual([]);
  });

  it("counts a core path once per module, however many files use it", () => {
    const files = ["inventory/a/X.ts", "inventory/b/Y.ts"];
    const read = () => 'import type { Item } from "@/types";';
    expect(coreImportsIn(files, read)).toEqual(["inventory → @/types"]);
  });

  it("ignores specs when collecting core imports", () => {
    expect(
      coreImportsIn(
        ["inventory/X.test.tsx", "inventory/__tests__/Y.tsx"],
        () => 'import { api } from "@/lib/api/client";',
      ),
    ).toEqual([]);
  });
});
