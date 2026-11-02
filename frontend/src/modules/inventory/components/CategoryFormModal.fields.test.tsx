/**
 * The equipment fields section used to promise "Predefined fields · expand
 * with custom ones" over an empty list: a category created from the UI has
 * no predefined fields — only the module's built-in ones do. The subtitle
 * now says which of the two the list holds.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { render } from "@/test/utils";
import { CategoryFormModal } from "./CategoryFormModal";
import type { FieldDefinition } from "@/types";

vi.mock("@/modules/shared/hooks/useCategories", () => ({
  useCreateCategory: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateCategory: () => ({ mutate: vi.fn(), isPending: false }),
  useCategories: () => ({ data: [] }),
}));

const openEquipment = (fields: FieldDefinition[] = []) =>
  render(
    <CategoryFormModal
      isOpen
      onClose={vi.fn()}
      contextTag="equipment"
      editingCategory={
        fields.length
          ? ({ id: "c1", name: "Laptop", field_definitions: fields } as never)
          : null
      }
    />,
  );

const SERIAL: FieldDefinition = {
  key: "serial_number",
  label: "Serial Number",
  type: "text",
  visible: true,
  required: false,
  is_system: false,
};

describe("CategoryFormModal — the fields subtitle says what the list holds", () => {
  it("a category without predefined fields is not promised any", () => {
    openEquipment();

    expect(screen.getByText(/No predefined fields/)).toBeInTheDocument();
    expect(
      screen.queryByText("Predefined fields · expand with custom ones"),
    ).not.toBeInTheDocument();
  });

  it("a category that carries predefined fields shows the count, not the promise", () => {
    openEquipment([SERIAL]);

    expect(screen.getByText(/defined field/)).toBeInTheDocument();
    expect(screen.queryByText(/No predefined fields/)).not.toBeInTheDocument();
  });
});
