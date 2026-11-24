import { describe, expect, it } from "vitest";
import type { Item } from "@/types";
import { isEquipmentRecord } from "./equipmentRecord";

function record(over: Partial<Record<keyof Item, unknown>> = {}): Item {
  return {
    id: "item-1",
    name: "Laptop",
    quantity: "1",
    location_id: "loc-1",
    category: null,
    metadata: null,
    ...over,
  } as unknown as Item;
}

/**
 * The register answers "is this record equipment" once for the module's list,
 * the detail route and the core's product list. The screens reading the same
 * record ask the same question, in the same order and of the same fields, so a
 * record the register lists does not open as "not found" or wear product
 * wording on its own page.
 */
describe("isEquipmentRecord", () => {
  it("claims a record filed under a category carrying the equipment tag", () => {
    expect(
      isEquipmentRecord(record({ category: { context_tag: "equipment" } })),
    ).toBe(true);
  });

  it("keeps a record filed under an ordinary category an ordinary product", () => {
    // The category speaks first: the organization filed this record as an
    // ordinary product, and the namespace left in its metadata does not
    // overrule that.
    expect(
      isEquipmentRecord(
        record({
          category: { context_tag: null },
          metadata: { equipment: { equipment_status: "AVAILABLE" } },
        }),
      ),
    ).toBe(false);
  });

  it("claims an uncategorized record holding the equipment namespace", () => {
    expect(
      isEquipmentRecord(
        record({ metadata: { equipment: { equipment_status: "AVAILABLE" } } }),
      ),
    ).toBe(true);
  });

  it("claims a namespace that is a JSON null", () => {
    // `{"metadata": {"equipment": null}}` is a namespace the register lists:
    // the backend asks whether the key is SQL NULL, and a JSON null is not.
    // The answer follows the key's presence, not the value beside it.
    expect(isEquipmentRecord(record({ metadata: { equipment: null } }))).toBe(
      true,
    );
  });

  it("leaves a record with neither a category nor the namespace a product", () => {
    expect(isEquipmentRecord(record({ metadata: { color: "red" } }))).toBe(
      false,
    );
    expect(isEquipmentRecord(record({ metadata: null }))).toBe(false);
  });
});
