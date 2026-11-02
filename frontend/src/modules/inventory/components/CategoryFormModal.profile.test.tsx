/**
 * "e.g. Dairy, Drinks…" is a helpful example on a pantry and a wrong one
 * on a workspace that tracks server racks. The storage wizard has followed
 * the product profile since it was written; the category form did not.
 */
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { render } from "@/test/utils";
import { CategoryFormModal } from "./CategoryFormModal";

const activeProfile = { seed_profile: "equipment_wms" as string | null };

vi.mock("@/hooks/useActiveProfile", () => ({
  useActiveProfile: () => activeProfile,
}));

vi.mock("@/modules/shared/hooks/useCategories", () => ({
  useCreateCategory: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateCategory: () => ({ mutate: vi.fn(), isPending: false }),
  useCategories: () => ({ data: [] }),
}));

const open = () =>
  render(<CategoryFormModal isOpen editingCategory={null} onClose={vi.fn()} />);

describe("CategoryFormModal — the example follows the workspace", () => {
  it("suggests equipment on an equipment workspace", () => {
    activeProfile.seed_profile = "equipment_wms";
    open();

    expect(
      screen.getByPlaceholderText("e.g. Laptops, Racks…"),
    ).toBeInTheDocument();
  });

  it("suggests food on a pantry workspace", () => {
    activeProfile.seed_profile = "food_home";
    open();

    expect(
      screen.getByPlaceholderText("e.g. Dairy, Drinks…"),
    ).toBeInTheDocument();
  });

  it("falls back to the generic example when no profile is set", () => {
    activeProfile.seed_profile = null;
    open();

    expect(
      screen.getByPlaceholderText("e.g. Dairy, Drinks…"),
    ).toBeInTheDocument();
  });
});
