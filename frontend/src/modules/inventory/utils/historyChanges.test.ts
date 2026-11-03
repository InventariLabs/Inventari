import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import i18n from "@/test/mocks/i18n";

import { LABEL_ONLY_ACTIONS, READERS, parseChanges } from "./historyChanges";

const t = ((key: string, opts?: { defaultValue?: string }) => {
  const names: Record<string, string> = {
    "equipment:status.retired": "Retired",
    "equipment:status.available": "Available",
    "equipment:status.maintenance": "In service",
  };
  return names[key] ?? opts?.defaultValue ?? key;
}) as unknown as (key: string, opts?: Record<string, unknown>) => string;

describe("historyChanges STATUS_CHANGED", () => {
  it("reads the absence of a status as the dash, never as the sentinel", () => {
    // The register used to carry UNKNOWN as the old status, and the row
    // fell through to the raw dump: old_status: "UNKNOWN" — the model's
    // word for nothing, printed like a state nobody declared.
    const line = parseChanges(
      "STATUS_CHANGED",
      { old_status: "UNKNOWN", new_status: "RETIRED" },
      t,
    );

    expect(line).not.toContain("UNKNOWN");
    expect(line).toBe("— → Retired");
  });

  it("names a real transition the way the asset timeline does", () => {
    const line = parseChanges(
      "STATUS_CHANGED",
      { old_status: "AVAILABLE", new_status: "MAINTENANCE" },
      t,
    );

    expect(line).toBe("Available → In service");
  });

  it("reads a state the dictionary does not know as itself, not as nothing", () => {
    const line = parseChanges(
      "STATUS_CHANGED",
      { old_status: "UNKNOWN", new_status: "DECOMMISSIONED" },
      t,
    );

    expect(line).toBe("— → DECOMMISSIONED");
  });
});

describe("historyChanges UPDATED", () => {
  // The card's own translator is bound to `items`; the journal's answers
  // (booleans, enum codes, category words) live in `common` and
  // `categories`. Passing it through is what makes the card read what the
  // journal reads instead of `true`/`false` and eight characters of a UUID.
  const tCard = i18n.getFixedT(null, "items");

  it("reads a boolean as the catalogue's word, not as true/false", () => {
    const line = parseChanges(
      "UPDATED",
      {
        old: { meta_data: { warranty: true } },
        new: { meta_data: { warranty: false } },
      },
      tCard,
    );

    expect(line).toBe("Additional data › Warranty: Yes → No");
  });

  it("names a reference the write recorded a name beside", () => {
    const line = parseChanges(
      "UPDATED",
      {
        old: {
          category_id: "67d57628-1111-2222-3333-444455556666",
          category_name: "Dairy",
        },
        new: {
          category_id: "84f70f85-1111-2222-3333-444455556666",
          category_name: "Drinks",
        },
      },
      tCard,
    );

    expect(line).toBe("Category: Dairy → Drinks");
  });

  it("names a unit the write recorded a symbol beside", () => {
    const line = parseChanges(
      "UPDATED",
      {
        old: {
          uom_id: "e3aaac7f-6498-42b9-97ba-6fc199f9159c",
          uom_name: "szt.",
        },
        new: {
          uom_id: "a2bbbd8e-7498-42b9-97ba-6fc199f9159c",
          uom_name: "kg",
        },
      },
      tCard,
    );

    expect(line).toBe("Unit: szt. → kg");
  });

  it("reads a cleared reference as the dash, never as a truncated id", () => {
    const line = parseChanges(
      "UPDATED",
      {
        old: {
          category_id: "67d57628-1111-2222-3333-444455556666",
          category_name: "Dairy",
        },
        new: { category_id: null, category_name: null },
      },
      tCard,
    );

    expect(line).toBe("Category: Dairy → —");
  });

  it("never prints eight characters of an id nothing can name", () => {
    const line = parseChanges(
      "UPDATED",
      {
        old: { storage_location_id: "67d57628-1111-2222-3333-444455556666" },
        new: { storage_location_id: "84f70f85-1111-2222-3333-444455556666" },
      },
      tCard,
    );

    expect(line).not.toContain("67d57628");
    expect(line).not.toContain("84f70f85");
  });
});

describe("historyChanges CREATED_VIA_SCAN", () => {
  const tScan = ((key: string, opts?: Record<string, unknown>) => {
    const templates: Record<string, string> = {
      "items:history.createdViaScan.label":
        "Created by scanning label {{code}}",
      "items:history.createdViaScan.barcode":
        "Created by scanning barcode {{code}}",
      "items:history.createdViaScan.photo": "Created from a recognized photo",
    };
    const template = templates[key];
    if (!template) return key;
    return template.replace(
      "{{code}}",
      typeof opts?.code === "string" ? opts.code : "",
    );
  }) as unknown as (key: string, opts?: Record<string, unknown>) => string;

  it("names the label code the scan wrote, not a quantity it never wrote", () => {
    const line = parseChanges(
      "CREATED_VIA_SCAN",
      { label_code: "PL-4F2A", barcode: null, via_vision_ai: false },
      tScan,
    );

    expect(line).toBe("Created by scanning label PL-4F2A");
  });

  it("names the barcode when the scan matched one instead of a label", () => {
    const line = parseChanges(
      "CREATED_VIA_SCAN",
      { label_code: null, barcode: "5901234123457", via_vision_ai: false },
      tScan,
    );

    expect(line).toBe("Created by scanning barcode 5901234123457");
  });

  it("says the row came from a recognized photo when no code is in it", () => {
    const line = parseChanges(
      "CREATED_VIA_SCAN",
      { label_code: null, barcode: null, via_vision_ai: true },
      tScan,
    );

    expect(line).toBe("Created from a recognized photo");
  });

  it("stays quiet when the row carries nothing the scan can name", () => {
    const line = parseChanges("CREATED_VIA_SCAN", { quantity: 5 }, tScan);

    expect(line).toBe("");
  });
});

describe("historyChanges QUANTITY_INCREASED_VIA_SCAN", () => {
  const tScan = ((key: string, opts?: Record<string, unknown>) => {
    const templates: Record<string, string> = {
      "items:history.quantityIncreasedViaScan.barcode": "barcode: {{code}}",
    };
    const template = templates[key];
    if (!template) return key;
    return template.replace(
      "{{code}}",
      typeof opts?.code === "string" ? opts.code : "",
    );
  }) as unknown as (key: string, opts?: Record<string, unknown>) => string;

  it("reads the quantity change as a sentence, not a raw dump", () => {
    const line = parseChanges(
      "QUANTITY_INCREASED_VIA_SCAN",
      {
        barcode: "5901234123457",
        old_quantity: 2,
        new_quantity: 5,
        increment: 3,
      },
      tScan,
    );

    expect(line).not.toContain("old_quantity");
    expect(line).not.toContain("new_quantity");
    expect(line).not.toContain("increment:");
    expect(line).toContain("2 → 5");
    expect(line).toContain("(+3)");
  });

  it("names the barcode the scan matched", () => {
    const line = parseChanges(
      "QUANTITY_INCREASED_VIA_SCAN",
      {
        barcode: "5901234123457",
        old_quantity: 2,
        new_quantity: 5,
        increment: 3,
      },
      tScan,
    );

    expect(line).toContain("barcode: 5901234123457");
  });

  it("stays readable without a barcode", () => {
    const line = parseChanges(
      "QUANTITY_INCREASED_VIA_SCAN",
      { barcode: null, old_quantity: 0, new_quantity: 1, increment: 1 },
      tScan,
    );

    expect(line).toBe("0 → 1 (+1)");
  });
});

describe("historyChanges OPENED", () => {
  const tOpened = ((key: string, opts?: Record<string, unknown>) =>
    key === "items:history.openedLeft"
      ? `${String(opts?.amount)} left`
      : key) as unknown as (
    key: string,
    opts?: Record<string, unknown>,
  ) => string;

  it("says how much was left in the unit it was said in, with no ids or ISO times", () => {
    const line = parseChanges(
      "OPENED",
      {
        opened_at: "2026-10-15T20:50:16.824644+00:00",
        split_from: "71b90eb1-87d6-4d42-9d36-54702c09e2bb",
        left: 1.5,
        left_unit: "kg",
      },
      tOpened,
    );

    expect(line).toBe("1.5 kg left");
  });

  it("says nothing extra for a package that was only marked as opened", () => {
    expect(
      parseChanges(
        "OPENED",
        { opened_at: "2026-10-15T20:50:16+00:00" },
        tOpened,
      ),
    ).toBe("");
  });

  it("says nothing is left for an emptied package", () => {
    expect(parseChanges("OPENED", { left: 0 }, tOpened)).toBe(
      "items:history.openedNothingLeft",
    );
  });
});

describe("ItemAction ↔ READERS contract", () => {
  it("every ItemAction member has a reader or an explicit label-only declaration", () => {
    const pySource = readFileSync(
      resolve(process.cwd(), "../backend/app/core/contracts/_system_dtos.py"),
      "utf-8",
    );
    const enumBlock = pySource.match(
      /class ItemAction\(StrEnum\):([\s\S]*?)(?=\nclass )/,
    );
    expect(enumBlock).not.toBeNull();
    const members = [
      ...enumBlock![1].matchAll(/^\s+(\w+)\s*=\s*'(\w+)'/gm),
    ].map((m) => m[2]);
    expect(members.length).toBeGreaterThan(0);

    for (const action of members) {
      expect(
        action in READERS || LABEL_ONLY_ACTIONS.has(action),
        `ItemAction.${action} has no reader and no label-only declaration — add one to READERS or LABEL_ONLY_ACTIONS in historyChanges.ts`,
      ).toBe(true);
    }
  });
});

describe("historyChanges quantities carry the record's unit", () => {
  const grams = { symbol: "g", rounding: null };

  it("writes both sides of a quantity change in the unit", () => {
    const line = parseChanges(
      "QUANTITY_CHANGED",
      { old: 290.667, new: 499 },
      t,
      undefined,
      grams,
    );

    expect(line).toBe("290.667 g → 499 g");
  });

  it("writes a removal and a scan increment in the unit", () => {
    expect(parseChanges("USED", { qty: 120 }, t, undefined, grams)).toBe(
      "120 g",
    );
    expect(
      parseChanges(
        "QUANTITY_INCREASED_VIA_SCAN",
        { old_quantity: 1, new_quantity: 3, increment: 2 },
        t,
        undefined,
        grams,
      ),
    ).toBe("1 g → 3 g (+2 g)");
  });

  it("keeps the bare number for a record that has no unit", () => {
    expect(
      parseChanges("QUANTITY_CHANGED", { old: 2, new: 5 }, t, undefined, {
        symbol: null,
      }),
    ).toBe("2 → 5");
    expect(parseChanges("QUANTITY_CHANGED", { old: 2, new: 5 }, t)).toBe(
      "2 → 5",
    );
  });
});

describe("historyChanges QUANTITY_CHANGED — a production run", () => {
  it("names the run beside the reason code, not the code alone", () => {
    const line = parseChanges(
      "QUANTITY_CHANGED",
      {
        old: 5,
        new: 1,
        reason: "production_run",
        production_order_number: "PR/2026/0001",
      },
      t,
    );
    expect(line).toContain("PR/2026/0001");
  });
});
