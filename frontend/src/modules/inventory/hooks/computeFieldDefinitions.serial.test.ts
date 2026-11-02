import { describe, it, expect } from "vitest";
import { computeFieldDefinitions } from "./computeFieldDefinitions";
import type { CategoryDTO } from "@/types";

const baseContext = {
  selectedCategory: undefined,
  selectedStorage: undefined,
  uomCategoryName: null,
} as const;

const category = (context_tag: string | null) =>
  ({ id: "c-1", name: "Cat", context_tag }) as unknown as CategoryDTO;

const visible = (
  fields: ReturnType<typeof computeFieldDefinitions>,
  key: string,
) => fields.find((f) => f.key === key)?.visible;

/**
 * A serial number names one physical, uniquely numbered unit — equipment. A
 * jar of ketchup has none, so the form stops asking for it wherever it knows
 * the product is food: a food category, or a barcode the food database
 * recognised before any category was picked.
 */
describe("computeFieldDefinitions — the serial number belongs to equipment", () => {
  it.each(["food", "cold_storage", "dry_goods"])(
    "hides it under the %s category context",
    (tag) => {
      const fields = computeFieldDefinitions({
        ...baseContext,
        selectedCategory: category(tag),
      });
      expect(visible(fields, "serial_number")).toBe(false);
      expect(visible(fields, "expiry_date")).toBe(true);
    },
  );

  it("offers it under an equipment category", () => {
    const fields = computeFieldDefinitions({
      ...baseContext,
      selectedCategory: category("equipment"),
    });
    expect(visible(fields, "serial_number")).toBe(true);
    expect(visible(fields, "expiry_date")).toBe(false);
  });

  it("offers it where no category is picked and nothing says food", () => {
    expect(visible(computeFieldDefinitions(baseContext), "serial_number")).toBe(
      true,
    );
  });

  it("offers it under a category that carries no context at all", () => {
    const fields = computeFieldDefinitions({
      ...baseContext,
      selectedCategory: category(null),
    });
    expect(visible(fields, "serial_number")).toBe(true);
  });

  it("reads a food scan with no category as food", () => {
    const fields = computeFieldDefinitions({
      ...baseContext,
      scannedAsFood: true,
    });
    expect(visible(fields, "serial_number")).toBe(false);
    expect(visible(fields, "expiry_date")).toBe(true);
    expect(visible(fields, "freeze_date")).toBe(true);
  });

  it("lets a chosen category overrule the scan", () => {
    const fields = computeFieldDefinitions({
      ...baseContext,
      scannedAsFood: true,
      selectedCategory: category("equipment"),
    });
    expect(visible(fields, "serial_number")).toBe(true);
    expect(visible(fields, "expiry_date")).toBe(false);
  });
});
