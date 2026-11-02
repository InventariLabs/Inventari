import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import CategoryCreateModal from "./CategoryCreateModal";
import { useCreateCategory } from "@/modules/shared/hooks/useCategories";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/modules/shared/hooks/useCategories", () => ({
  useCreateCategory: vi.fn(),
}));

const mutate = vi.fn();

describe("CategoryCreateModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useCreateCategory).mockReturnValue({
      mutate,
      isPending: false,
    } as unknown as ReturnType<typeof useCreateCategory>);
  });

  it("refuses to create a category with no name", () => {
    render(<CategoryCreateModal onClose={vi.fn()} onSuccess={vi.fn()} />);
    expect(screen.getByRole("button", { name: /Create/i })).toBeDisabled();
  });

  it("creates the category and hands it back to the form that asked", async () => {
    const user = userEvent.setup();
    const onSuccess = vi.fn();
    const created = { id: "cat-1", name: "Spare parts" };
    mutate.mockImplementation(
      (_payload: unknown, opts: { onSuccess: (c: typeof created) => void }) => {
        opts.onSuccess(created);
      },
    );

    render(<CategoryCreateModal onClose={vi.fn()} onSuccess={onSuccess} />);
    await user.type(screen.getByRole("textbox"), "Spare parts");
    await user.click(screen.getByRole("button", { name: /Create/i }));

    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Spare parts" }),
      expect.any(Object),
    );
    expect(onSuccess).toHaveBeenCalledWith(created);
  });
});
