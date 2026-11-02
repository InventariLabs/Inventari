import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@/test/utils";
import ProductFormContent from "./ProductFormContent";
import { computeFieldDefinitions } from "@/modules/inventory/hooks/computeFieldDefinitions";
import type { FieldDefinition } from "@/types";

vi.mock("../UnifiedFieldRenderer", () => ({
  default: ({ fieldDefinitions }: { fieldDefinitions: FieldDefinition[] }) => (
    <div data-testid="renderer">
      {fieldDefinitions
        .filter((f) => f.visible)
        .map((f) => (
          <span key={f.key} data-testid={`field-${f.key}`} />
        ))}
    </div>
  ),
}));

const nameField: FieldDefinition = {
  key: "name",
  label: "Product name",
  type: "text",
  visible: true,
  required: true,
  is_system: false,
};

describe("ProductFormContent — filing a product when it is created", () => {
  it("offers the category field even when nothing declares it", () => {
    // The picker is not a gift from whichever module happens to declare the
    // field. SYSTEM_FIELDS makes it visible by default, so a product can
    // always be filed — and the payload builder reads the same definition,
    // so what the form draws is what the save sends.
    const fields = computeFieldDefinitions({
      selectedCategory: undefined,
      selectedStorage: undefined,
      uomCategoryName: null,
    });
    const category = fields.find((f) => f.key === "category_id");
    expect(category?.visible).toBe(true);
  });

  it("renders the category picker the definitions offer", () => {
    render(
      <ProductFormContent
        formData={{ name: "" }}
        onChange={vi.fn()}
        errors={{}}
        fieldDefinitions={[
          nameField,
          {
            key: "category_id",
            label: "category",
            type: "select",
            visible: true,
            required: false,
            is_system: false,
          },
        ]}
      />,
    );
    expect(screen.getAllByTestId("field-category_id")).toHaveLength(1);
  });

  it("does not render a category field the definitions hide", () => {
    // A category's own field_definitions can hide the field — that is the
    // one way it goes away, and the renderer honours the same definition
    // the payload builder does.
    render(
      <ProductFormContent
        formData={{ name: "" }}
        onChange={vi.fn()}
        errors={{}}
        fieldDefinitions={[
          nameField,
          {
            key: "category_id",
            label: "category",
            type: "select",
            visible: false,
            required: false,
            is_system: false,
          },
        ]}
      />,
    );
    expect(screen.queryByTestId("field-category_id")).not.toBeInTheDocument();
  });

  it("keeps the expiry date visible on a category the food profile seeds", () => {
    // Every category the food_home profile seeds carries 'cold_storage' or
    // 'dry_goods' as its context, while the date fields were gated on 'food'
    // alone — picking "Cheese" made EXPIRY DATE vanish together with the
    // value typed into it, in the same frame, without a word.
    const fields = computeFieldDefinitions({
      selectedCategory: {
        id: "c1",
        name: "Test category",
        is_active: true,
        is_module_owned: false,
        context_tag: "cold_storage",
      },
      selectedStorage: undefined,
      uomCategoryName: null,
    });
    expect(fields.find((f) => f.key === "expiry_date")?.visible).toBe(true);
    expect(fields.find((f) => f.key === "freeze_date")?.visible).toBe(true);
    expect(fields.find((f) => f.key === "weight")?.visible).toBe(true);
  });

  it("keeps them visible on a dry-goods category too", () => {
    const fields = computeFieldDefinitions({
      selectedCategory: {
        id: "c2",
        name: "Test category",
        is_active: true,
        is_module_owned: false,
        context_tag: "dry_goods",
      },
      selectedStorage: undefined,
      uomCategoryName: null,
    });
    expect(fields.find((f) => f.key === "expiry_date")?.visible).toBe(true);
  });

  it("still hides the date fields behind a foreign context", () => {
    // The gate is about the vertical, not about being seeded: an equipment
    // category does not ask when the thing expires.
    const fields = computeFieldDefinitions({
      selectedCategory: {
        id: "c3",
        name: "Test category",
        is_active: true,
        is_module_owned: false,
        context_tag: "equipment",
      },
      selectedStorage: undefined,
      uomCategoryName: null,
    });
    expect(fields.find((f) => f.key === "expiry_date")?.visible).toBe(false);
  });
});
