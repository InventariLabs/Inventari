import { describe, it, expect } from "vitest";
import { computeFieldDefinitions } from "./computeFieldDefinitions";
import {
  makeLocationField,
  makeStorageSummary,
} from "@/test/factories/storage";

const baseContext = {
  selectedCategory: undefined,
  uomCategoryName: null,
} as const;

const from = { from_id: "wh", from_name: "Warehouse" };

const field = makeLocationField;

/**
 * A product field set on a warehouse or a rack applies to every location
 * inside it. The storages listing names what a location takes from above;
 * the form asks for it as it asks for the location's own fields.
 */
describe("computeFieldDefinitions — fields set on a level above the location", () => {
  it("asks for a custom field a location above set", () => {
    const shelf = makeStorageSummary({
      inherited_field_definitions: [
        {
          ...field("opened_on", { label: "Opened on", type: "date" }),
          ...from,
        },
      ],
    });

    const opened = computeFieldDefinitions({
      ...baseContext,
      selectedStorage: shelf,
    }).find((f) => f.key === "opened_on");

    expect(opened).toMatchObject({
      label: "Opened on",
      type: "date",
      is_custom: true,
    });
  });

  it("shows a tracked field a location above set, as one set here would", () => {
    const shelf = makeStorageSummary({
      context_schema: ["notes"],
      inherited_context_schema: [{ key: "barcode", ...from }],
    });

    const visible = computeFieldDefinitions({
      ...baseContext,
      selectedStorage: shelf,
    })
      .filter((f) => f.visible)
      .map((f) => f.key);

    expect(visible).toContain("barcode");
    // The schema still restricts: a field neither level set stays hidden.
    expect(visible).not.toContain("serial_number");
  });

  it("lets the location's own definition win a clash with an inherited one", () => {
    const shelf = makeStorageSummary({
      field_definitions: [
        field("batch", { label: "Batch here", required: true }),
      ],
      inherited_field_definitions: [
        { ...field("batch", { label: "Batch above" }), ...from },
      ],
    });

    const batches = computeFieldDefinitions({
      ...baseContext,
      selectedStorage: shelf,
    }).filter((f) => f.key === "batch");

    expect(batches).toHaveLength(1);
    expect(batches[0]).toMatchObject({ label: "Batch here", required: true });
  });
});
