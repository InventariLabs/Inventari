/**
 * The rule is "state a scope", so these pin what counts as stating one — and
 * that a call spread over several lines, or holding a call of its own, is
 * still read whole.
 */
import { describe, expect, it } from "vitest";

import {
  callArguments,
  diffBaseline,
  generalSliceIn,
  isScanned,
  isStockAction,
  unscopedIn,
} from "./check-storage-scope.mjs";

describe("callArguments", () => {
  it("reads an empty argument list", () => {
    expect(callArguments("useStorages()")).toEqual([{ index: 0, args: "" }]);
  });

  it("reads arguments spread over several lines", () => {
    const text = "useStorages(\n  undefined,\n  { usage: 'all' },\n)";
    expect(callArguments(text)[0].args).toContain("usage");
  });

  it("reads past a nested call", () => {
    const text = "useStorages(undefined, { moduleScope: pick(mod) })";
    expect(callArguments(text)[0].args).toContain("moduleScope");
  });

  it("does not mistake useStoragesTree for useStorages", () => {
    expect(callArguments("useStoragesTree()")).toEqual([]);
  });
});

describe("unscopedIn", () => {
  it("reports a bare call", () => {
    expect(unscopedIn("a.tsx", "const { data } = useStorages();")).toEqual([
      { file: "a.tsx", line: 1 },
    ]);
  });

  it("reports a bare call with whitespace inside the parens", () => {
    expect(unscopedIn("a.tsx", "useStorages(\n)")).toHaveLength(1);
  });

  it("accepts a context tag", () => {
    expect(unscopedIn("a.tsx", 'useStorages("equipment")')).toEqual([]);
  });

  it("accepts explicit options", () => {
    expect(
      unscopedIn("a.tsx", "useStorages(undefined, { usage: 'all' })"),
    ).toEqual([]);
    expect(
      unscopedIn("a.tsx", "useStorages(undefined, { excludeModuleContexts })"),
    ).toEqual([]);
  });

  it("says nothing about useScopedStorages, which states its own scope", () => {
    expect(unscopedIn("a.tsx", "useScopedStorages()")).toEqual([]);
  });

  it("ignores a call written inside a comment", () => {
    expect(
      unscopedIn("a.tsx", "// useStorages() used to be called here\n"),
    ).toEqual([]);
  });

  it("carries the line the call sits on", () => {
    const text = ["const a = 1;", "", "const { data } = useStorages();"].join(
      "\n",
    );
    expect(unscopedIn("a.tsx", text)[0].line).toBe(3);
  });
});

describe("isScanned", () => {
  it("reads hooks as well as components, and skips tests", () => {
    expect(isScanned("hooks/useX.ts")).toBe(true);
    expect(isScanned("hooks/useX.test.ts")).toBe(false);
    expect(isScanned("a.json")).toBe(false);
  });
});

describe("diffBaseline", () => {
  it("passes what the baseline holds and fails a new file", () => {
    const base = { "a.tsx": 1 };
    expect(diffBaseline([{ file: "a.tsx", line: 1 }], base).added).toEqual([]);
    expect(diffBaseline([{ file: "b.tsx", line: 1 }], base).added).toHaveLength(
      1,
    );
  });

  it("fails a second bare call in a file the baseline holds", () => {
    const { added } = diffBaseline(
      [
        { file: "a.tsx", line: 1 },
        { file: "a.tsx", line: 9 },
      ],
      { "a.tsx": 1 },
    );
    expect(added).toEqual([{ key: "a.tsx", was: 1, now: 2 }]);
  });
});

describe("generalSliceIn", () => {
  const receive = "modules/warehouse/pages/ReceiveGoodsPage.tsx";
  const draft = "modules/warehouse/hooks/useActionDraft.ts";

  it("knows the stock actions by their files", () => {
    expect(isStockAction(receive)).toBe(true);
    expect(isStockAction("modules/warehouse/pages/IssueGoodsPage.tsx")).toBe(
      true,
    );
    expect(isStockAction(draft)).toBe(true);
    expect(isStockAction("modules/warehouse/pages/DocumentsPage.tsx")).toBe(
      false,
    );
  });

  it("refuses the general pair on a receipt", () => {
    expect(generalSliceIn(receive, "useScopedStorages();")).toEqual([
      { file: receive, line: 1 },
    ]);
  });

  it("accepts the stock pair", () => {
    expect(
      generalSliceIn(
        receive,
        'useScopedStorages(undefined, { purpose: "stock" })',
      ),
    ).toEqual([]);
  });

  it("refuses a scope the organization's policy decides", () => {
    const text =
      "useStoragesTree(undefined, showModuleData ? undefined : { excludeModuleContexts: true })";
    expect(generalSliceIn(draft, text)).toHaveLength(1);
  });

  it("accepts a fixed exclusion of module places", () => {
    expect(
      generalSliceIn(
        draft,
        "useStoragesTree(undefined, { excludeModuleContexts: true })",
      ),
    ).toEqual([]);
  });

  it("leaves every other screen to the first rule", () => {
    expect(
      generalSliceIn(
        "modules/warehouse/pages/DocumentsPage.tsx",
        "useScopedStorages()",
      ),
    ).toEqual([]);
  });
});
