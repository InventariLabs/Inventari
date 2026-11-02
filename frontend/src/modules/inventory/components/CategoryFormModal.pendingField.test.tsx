/**
 * A custom field typed into the builder and never confirmed with "Add field"
 * was dropped when the category was saved, and the form reported success.
 */
import { screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render } from "@/test/utils";
import { CategoryFormModal } from "./CategoryFormModal";

const createMutate = vi.hoisted(() => vi.fn());
vi.mock("@/modules/shared/hooks/useCategories", () => ({
  useCreateCategory: () => ({ mutate: createMutate, isPending: false }),
  useUpdateCategory: () => ({ mutate: vi.fn(), isPending: false }),
  useCategories: () => ({ data: [] }),
}));

const typeFieldAndSave = (label: string) => {
  fireEvent.change(screen.getByLabelText(/category name/i), {
    target: { value: "Fasteners" },
  });
  fireEvent.click(screen.getByRole("button", { name: /custom field/i }));
  fireEvent.click(screen.getByRole("button", { name: /add custom field/i }));
  fireEvent.change(screen.getByLabelText("Field label"), {
    target: { value: label },
  });
  fireEvent.click(screen.getByRole("button", { name: /^save$|^create$/i }));
};

describe("CategoryFormModal — an unconfirmed custom field", () => {
  beforeEach(() => createMutate.mockClear());

  it("is saved with the category", () => {
    render(
      <CategoryFormModal isOpen onClose={vi.fn()} editingCategory={null} />,
    );

    typeFieldAndSave("Thread size");

    expect(createMutate).toHaveBeenCalledTimes(1);
    expect(createMutate.mock.calls[0][0].field_definitions).toEqual([
      expect.objectContaining({ key: "thread_size", label: "Thread size" }),
    ]);
  });
});
