import { describe, expect, it } from "vitest";

import i18n from "@/test/mocks/i18n";
import type { TranslateFn } from "@/types/i18n";
import type { CategoryDTO, Item } from "@/types";

import { groupItemsByCategory } from "./groupItemsByCategory";

const t = i18n.t.bind(i18n) as unknown as TranslateFn;

function category(overrides: Partial<CategoryDTO> = {}): CategoryDTO {
  return {
    id: "cat-deli",
    name: "Deli",
    code: "deli",
    is_active: true,
    is_module_owned: false,
    ...overrides,
    context_tag: null,
    icon: null,
    sort_order: 0,
    meta_data: null,
  } as CategoryDTO;
}

function item(
  overrides: Omit<Partial<Item>, "category"> & {
    category?: CategoryDTO | null;
  },
): Item {
  return {
    id: "i-1",
    category_id: "cat-deli",
    ...overrides,
  } as unknown as Item;
}

describe("groupItemsByCategory", () => {
  it("names a group header the way the picker does", () => {
    // The rows' group headers used to print the raw record name, so the
    // products list read "SPICES AND HERBS" over rows that say
    // "PRZYPRAWY I ZIOŁA" — one screen, two words, the exact shape of
    // the picker-versus-bulk-edit split.
    const deli = category();
    const groups = groupItemsByCategory(
      [item({ category: deli })],
      [deli],
      "No category",
      t,
    );
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe("Cold cuts");
  });

  it("keeps a code-less category's own name", () => {
    const homemade = category({ code: null, name: "Homemade sauces" });
    const groups = groupItemsByCategory(
      [item({ category: homemade })],
      [homemade],
      "No category",
      t,
    );
    expect(groups[0].label).toBe("Homemade sauces");
  });
});
