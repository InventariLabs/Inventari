import { describe, it, expect } from "vitest";
import {
  breakingChanges,
  contractFromSources,
  guideFindings,
  readGuideTable,
} from "./check-module-contract.mjs";

const INTERFACES = `
import type { SlotDataMap } from "./slotProps";

export interface ModuleRoute {
  path: string;
  exact?: boolean;
}

export interface SlotContribution {
  slot: keyof SlotDataMap;
  component: unknown;
  priority?: number;
}

export interface FrontendModule {
  name: string;
  routes: ModuleRoute[];
  slots?: SlotContribution[];
  theme?: { cssVariables: Record<string, string> };
  searchProvider?: SearchProvider;
}

export type SearchProvider = (query: string) => Promise<SearchResult[]>;

export interface SearchResult {
  id: string;
  title: string;
}
`;

const SLOTS = `
import type { Item, ScannedTemplate } from "./types";

export interface SlotDataMap {
  item_edit_extra: {
    item: Item;
    formData: Record<string, unknown>;
    handleInputChange: (field: string, value: unknown) => void;
    storageType?: string;
  };
  stock_action_extra: {
    barcode: string;
    template: ScannedTemplate | undefined;
  };
  global_notifications: Record<string, never>;
}
`;

const TYPES = `
export interface Item {
  name: string;
  quantity: string;
}

export interface ScannedTemplate {
  name: string;
  barcode?: string | null;
}
`;

function contract({
  interfaces = INTERFACES,
  slots = SLOTS,
  types = TYPES,
} = {}) {
  return contractFromSources(
    {
      "/virtual/moduleInterfaces.ts": interfaces,
      "/virtual/slotProps.ts": slots,
      "/virtual/types.ts": types,
    },
    "/virtual/moduleInterfaces.ts",
    "/virtual/slotProps.ts",
  );
}

const GUIDE = `# Guide

### Complete Slot Reference

| Slot name | Render location | Props shape | Status |
|---|---|---|---|
| \`item_edit_extra\` | Item modal | \`item\`, \`formData\`, \`handleInputChange(field, value)\`, \`storageType?\` | Active |
| \`stock_action_extra\` | Stock action sheet | \`barcode\`, \`template\` | Active |
| \`global_notifications\` | Notification layer | \`{}\` | Render site only (extension point) |

> **Status semantics — what does "Active" vs "Extension point" mean for you?**
`;

// Every case builds one to three TypeScript programs, and each program parses
// the standard library from disk: about a second of CPU a case on an idle
// host, and 15 s when another full suite shares the machine. The budget
// covers that load; it is this file's own, not the suite's.
describe("check-module-contract", { timeout: 60_000 }, () => {
  it("records every slot, its props and their resolved types", () => {
    const recorded = contract();

    expect(Object.keys(recorded.slotDataMap.props)).toEqual([
      "item_edit_extra",
      "stock_action_extra",
      "global_notifications",
    ]);

    const item = recorded.slotDataMap.props.item_edit_extra;
    expect(item.obj.formData).toEqual({
      optional: false,
      type: { ext: "Record", args: ["string", "unknown"] },
    });
    expect(item.obj.storageType).toEqual({
      optional: true,
      type: { union: ["string", "undefined"] },
    });
    // The slot's `item` prop is `Item`; the snapshot holds the fields `Item`
    // declares, not the annotation's spelling.
    expect(item.obj.item.type.obj).toEqual({
      name: { optional: false, type: "string" },
      quantity: { optional: false, type: "string" },
    });

    // `Record<string, never>` is an empty slot written as a type: no named
    // props, but the type itself is part of the contract.
    expect(recorded.slotDataMap.props.global_notifications).toEqual({
      ext: "Record",
      args: ["string", "never"],
    });

    // A named type two references deep is expanded too.
    const template = recorded.slotDataMap.props.stock_action_extra.obj.template;
    expect(template.type.union[1].obj.name).toEqual({
      optional: false,
      type: "string",
    });

    expect(recorded.frontendModule.props.routes.optional).toBe(false);
    expect(recorded.frontendModule.props.routes.type.array.obj.path).toEqual({
      optional: false,
      type: "string",
    });
    expect(recorded.slotContribution.props.priority.optional).toBe(true);
    expect(
      recorded.frontendModule.props.searchProvider.type.fn.params,
    ).toEqual([{ name: "query", optional: false, type: "string" }]);
  });

  it("passes an added slot, an added prop and a required -> optional change", () => {
    const before = contract();
    const after = contract({
      interfaces: INTERFACES.replace("component: unknown", "component?: unknown"),
      slots: SLOTS.replace(
        "    storageType?: string;",
        "    storageType?: string;\n    categoryContextTag?: string;",
      ).replace(
        "  global_notifications: Record<string, never>;",
        "  global_notifications: Record<string, never>;\n  dashboard_widgets: { organizationId: string };",
      ),
    });

    expect(breakingChanges(before, after)).toEqual([]);
  });

  it("passes an optional field added inside an inline object and a referenced one", () => {
    const before = contract();
    const after = contract({
      interfaces: INTERFACES.replace(
        "  exact?: boolean;",
        "  exact?: boolean;\n  label?: string;",
      ).replace(
        "theme?: { cssVariables: Record<string, string> };",
        "theme?: { cssVariables: Record<string, string>; extra?: string };",
      ),
    });

    expect(breakingChanges(before, after)).toEqual([]);
  });

  it("passes a required member becoming optional and a union member added", () => {
    const before = contract();
    const after = contract({
      interfaces: INTERFACES.replace("  path: string;", "  path?: string;"),
      slots: SLOTS.replace("barcode: string;", "barcode: string | number;"),
    });

    expect(breakingChanges(before, after)).toEqual([]);
  });

  it("fails null swapped for undefined on a nullable prop", () => {
    // The old union member is gone: a module testing `=== undefined` no
    // longer sees the value the contract used to promise.
    const before = contract();
    const after = contract({
      slots: SLOTS.replace(
        "template: ScannedTemplate | undefined;",
        "template: ScannedTemplate | null;",
      ),
    });

    expect(breakingChanges(before, after)).toEqual([
      "slotDataMap.stock_action_extra.template: union member undefined removed",
    ]);
  });

  it("fails undefined swapped for null on a nullable prop", () => {
    const before = contract({
      slots: SLOTS.replace(
        "template: ScannedTemplate | undefined;",
        "template: ScannedTemplate | null;",
      ),
    });
    const after = contract();

    expect(breakingChanges(before, after)).toEqual([
      "slotDataMap.stock_action_extra.template: union member null removed",
    ]);
  });

  it("fails a removed prop, which is also what a rename looks like", () => {
    const before = contract();
    const after = contract({
      slots: SLOTS.replace("    formData: Record<string, unknown>;\n", ""),
    });

    expect(breakingChanges(before, after)).toEqual([
      "slotDataMap.item_edit_extra.formData: removed (or renamed)",
    ]);
  });

  it("fails a prop whose type changed", () => {
    const before = contract();
    const after = contract({
      slots: SLOTS.replace("barcode: string;", "barcode: number;"),
    });

    expect(breakingChanges(before, after)).toEqual([
      "slotDataMap.stock_action_extra.barcode: type string -> number",
    ]);
  });

  it("fails a type change inside a referenced shape the annotation does not spell", () => {
    // `routes: ModuleRoute[]` does not say `path: string`; the module reads it.
    const before = contract();
    const after = contract({
      interfaces: INTERFACES.replace("  path: string;", "  path: number;"),
    });

    expect(breakingChanges(before, after)).toEqual([
      "frontendModule.routes[].path: type string -> number",
    ]);
  });

  it("fails a type change on a shape another package of the tree declares", () => {
    // `template: ScannedTemplate | undefined` keeps its annotation while the
    // interface it names changes.
    const before = contract();
    const after = contract({
      types: TYPES.replace("  name: string;\n  barcode?", "  name: number;\n  barcode?"),
    });

    expect(breakingChanges(before, after)).toEqual([
      "slotDataMap.stock_action_extra.template.name: type string -> number",
    ]);
  });

  it("fails a changed index signature", () => {
    const before = contract();
    const after = contract({
      slots: SLOTS.replace(
        "global_notifications: Record<string, never>",
        "global_notifications: Record<string, string>",
      ),
    });

    expect(breakingChanges(before, after)).toEqual([
      "slotDataMap.global_notifications<arg 1>: type never -> string",
    ]);
  });

  it("fails an optional prop that became required", () => {
    const before = contract();
    const after = contract({
      interfaces: INTERFACES.replace("priority?: number", "priority: number"),
    });

    // `SlotContribution` is recorded where it is declared and where
    // `FrontendModule.slots` embeds it; both point at the same break.
    expect(breakingChanges(before, after)).toEqual([
      "frontendModule.slots[].priority: optional -> required",
      "slotContribution.priority: optional -> required",
    ]);
  });

  it("fails a new required field at any depth — only optional fields may be added", () => {
    const before = contract();
    const after = contract({
      types: TYPES.replace("  quantity: string;", "  quantity: string;\n  sku: string;"),
    });

    expect(breakingChanges(before, after)).toEqual([
      "slotDataMap.item_edit_extra.item.sku: new required field " +
        "(only optional fields may be added)",
    ]);
  });

  it("fails a slot removed from the map, which is also what a rename looks like", () => {
    const before = contract();
    const after = contract({
      slots: SLOTS.replace("item_edit_extra", "item_edit_extra_renamed"),
    });

    expect(breakingChanges(before, after)).toEqual([
      'frontendModule.slots[].slot: union member "item_edit_extra" removed',
      'slotContribution.slot: union member "item_edit_extra" removed',
      "slotDataMap.item_edit_extra: slot removed (or renamed)",
    ]);
  });

  it("fails a parameter added to a contributed function, and passes an optional one", () => {
    const before = contract();
    const required = contract({
      interfaces: INTERFACES.replace(
        "(query: string) =>",
        "(query: string, limit: number) =>",
      ),
    });
    expect(breakingChanges(before, required)).toEqual([
      "frontendModule.searchProvider(limit): new required parameter " +
        "(only optional parameters may be added)",
    ]);

    const optional = contract({
      interfaces: INTERFACES.replace(
        "(query: string) =>",
        "(query: string, limit?: number) =>",
      ),
    });
    expect(breakingChanges(before, optional)).toEqual([]);
  });

  it("reads the guide table, including props written as calls or braces", () => {
    expect(readGuideTable(GUIDE)).toEqual([
      {
        slot: "item_edit_extra",
        props: ["item", "formData", "handleInputChange", "storageType"],
        optional: ["storageType"],
        status: "Active",
      },
      {
        slot: "stock_action_extra",
        props: ["barcode", "template"],
        optional: [],
        status: "Active",
      },
      {
        slot: "global_notifications",
        props: [],
        optional: [],
        status: "Render site only (extension point)",
      },
    ]);
  });

  it("fails a guide row with no slot and a prop the slot does not carry", () => {
    const slots = contract().slotDataMap.props;
    const rows = readGuideTable(GUIDE);
    rows[0].props.push("listId");
    rows.push({ slot: "storage_stock_action", props: [], status: "Active" });

    expect(
      guideFindings(
        slots,
        rows,
        new Set(["item_edit_extra", "stock_action_extra"]),
      ),
    ).toEqual([
      "GUIDE UNKNOWN PROP  item_edit_extra.listId — the slot does not pass it",
      "GUIDE UNKNOWN SLOT  storage_stock_action — not in SlotDataMap",
    ]);
  });

  it("fails a row that leaves out a prop the slot passes", () => {
    const slots = contract().slotDataMap.props;
    const rows = readGuideTable(GUIDE.replace("\`formData\`, ", ""));

    expect(
      guideFindings(
        slots,
        rows,
        new Set(["item_edit_extra", "stock_action_extra"]),
      ),
    ).toEqual([
      "GUIDE MISSING PROP  item_edit_extra.formData — the slot passes it, the row does not list it",
    ]);
  });

  it("fails a prop marked optional the other way round", () => {
    const slots = contract().slotDataMap.props;
    const rows = readGuideTable(
      GUIDE.replace("\`storageType?\`", "\`storageType\`").replace(
        "\`barcode\`",
        "\`barcode?\`",
      ),
    );

    expect(
      guideFindings(
        slots,
        rows,
        new Set(["item_edit_extra", "stock_action_extra"]),
      ),
    ).toEqual([
      "GUIDE OPTIONAL  item_edit_extra.storageType — the row says required, the type says optional",
      "GUIDE OPTIONAL  stock_action_extra.barcode — the row says optional, the type says required",
    ]);
  });

  it("fails a slot with no row in the table", () => {
    const slots = contract().slotDataMap.props;
    const rows = readGuideTable(GUIDE).filter(
      (row) => row.slot !== "global_notifications",
    );

    expect(
      guideFindings(
        slots,
        rows,
        new Set(["item_edit_extra", "stock_action_extra"]),
      ),
    ).toEqual(["GUIDE MISSING  global_notifications"]);
  });

  it("fails a status that no longer describes the tree", () => {
    const slots = contract().slotDataMap.props;
    const rows = readGuideTable(GUIDE);

    expect(guideFindings(slots, rows, new Set())).toEqual([
      'GUIDE STATUS  item_edit_extra — table says "Active", no in-tree module contributes to it',
      'GUIDE STATUS  stock_action_extra — table says "Active", no in-tree module contributes to it',
    ]);
    expect(
      guideFindings(
        slots,
        rows,
        new Set(["item_edit_extra", "stock_action_extra"]),
      ),
    ).toEqual([]);
    expect(
      guideFindings(
        slots,
        rows,
        new Set(["item_edit_extra", "stock_action_extra", "global_notifications"]),
      ),
    ).toEqual([
      'GUIDE STATUS  global_notifications — table says "Render site only (extension point)", an in-tree module contributes to it',
    ]);
  });
});
