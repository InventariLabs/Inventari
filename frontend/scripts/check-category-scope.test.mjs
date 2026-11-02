import { describe, expect, it } from "vitest";

import {
  callArguments,
  unscopedIn,
  isScanned,
} from "./check-category-scope.mjs";

/**
 * The scanner's job is to read a call, not to understand it: a bare
 * `useCategories()` is the finding, and everything that states a scope is
 * not. These cases pin the two mistakes that would make the gate useless —
 * reading a multi-line call as bare, and reading a scoped hook as the raw
 * one.
 */

const rel = "modules/warehouse/components/Example.tsx";

describe("check-category-scope", () => {
  it("fires on a bare call", () => {
    expect(unscopedIn(rel, "const { data } = useCategories();")).toEqual([
      { file: rel, line: 1 },
    ]);
  });

  it("does not fire when the call names its scope", () => {
    const source = [
      "const { data } = useCategories(undefined, undefined, false);",
      "const { scoped } = useScopedCategories(keepId);",
      "const { data } = useAllCategories();",
    ].join("\n");
    expect(unscopedIn(rel, source)).toEqual([]);
  });

  it("reads a multi-line bare call as one finding", () => {
    const source = "const { data } = useCategories(\n);";
    expect(unscopedIn(rel, source)).toEqual([{ file: rel, line: 1 }]);
  });

  it("reads a multi-line scoped call as scoped", () => {
    const source = [
      "const { data } = useCategories(",
      "  undefined,",
      "  undefined,",
      "  excludeModuleContexts,",
      "  true,",
      ");",
    ].join("\n");
    expect(unscopedIn(rel, source)).toEqual([]);
  });

  it("keeps a nested call in an argument from closing the outer one", () => {
    const source =
      "const { data } = useCategories(pickType(), true, false, true);";
    expect(callArguments(source)).toHaveLength(1);
    expect(unscopedIn(rel, source)).toEqual([]);
  });

  it("does not see a call inside a comment", () => {
    expect(unscopedIn(rel, "// useCategories() used to be here")).toEqual([]);
  });

  it("never matches the scoped twin", () => {
    expect(unscopedIn(rel, "useScopedCategories()")).toEqual([]);
    expect(unscopedIn(rel, "useAllCategories()")).toEqual([]);
  });

  it("does not scan test files", () => {
    expect(isScanned("modules/warehouse/Example.test.tsx")).toBe(false);
    expect(isScanned("modules/warehouse/Example.tsx")).toBe(true);
  });
});
