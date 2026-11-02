/**
 * FieldDefinition type union extension.
 *
 * The backend Literal (backend/app/schemas/category.py) was extended from
 * 5 to 9 types: text, number, date, select, boolean, textarea, file, money,
 * multi-select. The frontend type union must mirror this so TypeScript
 * accepts presets and category fields returned by the API.
 *
 * These tests are type-level only (compile-time). If this file compiles,
 * the union is correct.
 */

import { describe, it, expect } from "vitest";
import type { FieldDefinition } from "./core";

describe("FieldDefinition type union", () => {
  it("accepts the existing 5 types", () => {
    const samples: FieldDefinition[] = [
      {
        key: "a",
        label: "A",
        type: "text",
        visible: true,
        is_system: false,
        required: false,
      },
      {
        key: "b",
        label: "B",
        type: "number",
        visible: true,
        is_system: false,
        required: false,
      },
      {
        key: "c",
        label: "C",
        type: "date",
        visible: true,
        is_system: false,
        required: false,
      },
      {
        key: "d",
        label: "D",
        type: "select",
        options: ["x"],
        visible: true,
        is_system: false,
        required: false,
      },
      {
        key: "e",
        label: "E",
        type: "textarea",
        visible: true,
        is_system: false,
        required: false,
      },
    ];
    expect(samples).toHaveLength(5);
  });

  it("accepts the file, money, multi-select and boolean types", () => {
    const samples: FieldDefinition[] = [
      {
        key: "f",
        label: "F",
        type: "file",
        visible: true,
        is_system: false,
        required: false,
      },
      {
        key: "g",
        label: "G",
        type: "money",
        default_currency: "EUR",
        visible: true,
        is_system: false,
        required: false,
      },
      {
        key: "h",
        label: "H",
        type: "multi-select",
        options: ["x", "y"],
        visible: true,
        is_system: false,
        required: false,
      },
      {
        key: "i",
        label: "I",
        type: "boolean",
        visible: true,
        is_system: false,
        required: false,
      },
    ];
    expect(samples).toHaveLength(4);
  });

  it("FieldDefinition accepts default_currency", () => {
    const f: FieldDefinition = {
      key: "deposit",
      label: "Deposit",
      type: "money",
      default_currency: "USD",
      visible: true,
      is_system: false,
      required: false,
    };
    expect(f.default_currency).toBe("USD");
  });

  it("FieldDefinition accepts options (already supported)", () => {
    const f: FieldDefinition = {
      key: "allergens",
      label: "Allergens",
      type: "multi-select",
      options: ["Gluten", "Lactose"],
      visible: true,
      is_system: false,
      required: false,
    };
    expect(f.options).toEqual(["Gluten", "Lactose"]);
  });
});
