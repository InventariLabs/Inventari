import { describe, expect, it } from "vitest";
import { filterVisibleFields } from "../pages/AddEquipmentPage";
import type { FieldDefinition } from "@/types";

describe("filterVisibleFields", () => {
  it("drops definitions without a type (category_id leak)", () => {
    // The persisted `category_id` visibility flag has no `type` and no
    // `label`; it used to render as an unlabelled text input in the top
    // left of the category card.
    const fields = [
      { key: "category_id", visible: true },
      {
        key: "serial_number",
        type: "text",
        label: "Serial Number",
        visible: true,
      },
    ] as unknown as FieldDefinition[];
    expect(filterVisibleFields(fields).map((f) => f.key)).toEqual([
      "serial_number",
    ]);
  });

  it("keeps visible fields and drops explicitly invisible ones", () => {
    const fields = [
      { key: "a", type: "text", label: "A", visible: true },
      { key: "b", type: "text", label: "B", visible: false },
    ] as FieldDefinition[];
    expect(filterVisibleFields(fields).map((f) => f.key)).toEqual(["a"]);
  });
});
