/**
 * A category names the order its new products' stock leaves in, so a reader
 * who files every perishable under one category sets FEFO once rather than
 * on each product. An equipment category does not ask: assets are not drawn
 * by date.
 */
import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@/test/utils";
import { CategoryFormModal } from "./CategoryFormModal";

const create = vi.fn();
const update = vi.fn();

vi.mock("@/modules/shared/hooks/useCategories", () => ({
  useCreateCategory: () => ({ mutate: create, isPending: false }),
  useUpdateCategory: () => ({ mutate: update, isPending: false }),
  useCategories: () => ({ data: [] }),
}));

describe("CategoryFormModal — the issue order for new products", () => {
  beforeEach(() => {
    create.mockReset();
    update.mockReset();
  });

  it("sends FEFO chosen on a new category", () => {
    render(
      <CategoryFormModal isOpen onClose={vi.fn()} editingCategory={null} />,
    );

    fireEvent.change(screen.getByRole("textbox", { name: /name/i }), {
      target: { value: "Chilled" },
    });
    expect(screen.getByRole("radio", { name: "FIFO" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    fireEvent.click(screen.getByRole("radio", { name: "FEFO" }));
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Chilled",
        default_removal_strategy: "FEFO",
      }),
      expect.anything(),
    );
  });

  it("shows the default a category already has", () => {
    render(
      <CategoryFormModal
        isOpen
        onClose={vi.fn()}
        editingCategory={
          {
            id: "c1",
            name: "Chilled",
            default_removal_strategy: "FEFO",
          } as never
        }
      />,
    );

    expect(screen.getByRole("radio", { name: "FEFO" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("an equipment category does not ask", () => {
    render(
      <CategoryFormModal
        isOpen
        onClose={vi.fn()}
        editingCategory={null}
        contextTag="equipment"
      />,
    );

    expect(
      screen.queryByRole("radiogroup", {
        name: "Issue order for new products",
      }),
    ).not.toBeInTheDocument();
  });
});
