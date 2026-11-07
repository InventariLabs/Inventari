import { describe, it, expect } from "vitest";
import { computeFieldDefinitions } from "./computeFieldDefinitions";
import type { CategoryDTO } from "@/types";

const withDefinitions = (field_definitions: unknown[]) =>
  ({
    id: "c-1",
    name: "Laptop",
    context_tag: null,
    field_definitions,
  }) as unknown as CategoryDTO;

const compute = (selectedCategory: CategoryDTO) =>
  computeFieldDefinitions({
    selectedCategory,
    selectedStorage: undefined,
    uomCategoryName: null,
  });

describe("computeFieldDefinitions — a module's visibility flag", () => {
  it("keeps the translated system label when the flag carries a plain label", () => {
    // A module declares {key, label, visible} for a built-in column. The
    // label there names the column for API clients; the form speaks the
    // reader's language through the system field's own label.
    const fields = compute(
      withDefinitions([
        { key: "category_id", label: "Category", visible: true },
      ]),
    );
    const field = fields.find((f) => f.key === "category_id");
    expect(field?.label).toBe("itemCategory");
    expect(field?.visible).toBe(true);
  });

  it("still lets a typed definition rename a system field", () => {
    const fields = compute(
      withDefinitions([
        { key: "category_id", label: "Kind", type: "text", visible: true },
      ]),
    );
    expect(fields.find((f) => f.key === "category_id")?.label).toBe("Kind");
  });
});
