import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import "@/i18n/config";
import type { FieldDefinition, UomCategory } from "@/types";
import { DefaultInputField } from "./DefaultInputField";

const COUNT: UomCategory[] = [
  {
    id: "cat-unit",
    name: "Unit",
    uoms: [
      {
        id: "uom-pcs",
        name: "piece",
        symbol: "pcs",
        factor: "1",
        rounding: "1",
        is_reference: true,
        is_system: false,
        category_id: "cat-unit",
      },
    ],
  },
];

const quantity: FieldDefinition = {
  key: "quantity",
  type: "number",
  label: "fields.quantity",
  visible: true,
  required: false,
  is_system: true,
  is_custom: false,
};

describe("DefaultInputField", () => {
  // The unit's hint stood as a plain paragraph under the input: a screen
  // reader on the quantity never heard what the number counts.
  it("reads the unit's hint as the quantity's description", () => {
    render(
      <DefaultInputField
        field={quantity}
        value="3"
        uomId="uom-pcs"
        uomCategories={COUNT}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("spinbutton")).toHaveAccessibleDescription(
      "Number of pieces of this product",
    );
  });
});
