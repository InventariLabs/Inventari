import { screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { render } from "@/test/utils";
import { ModelGridCard } from "@/modules/equipment/components/ModelGridCard";
import type { EquipmentModel } from "@/modules/equipment/api/equipment";

vi.mock("@/modules/shared/hooks/useCategories", () => ({
  useCategories: () => ({ data: [], isLoading: false }),
  useAllCategories: () => ({ data: [], isLoading: false }),
}));

const model = {
  id: "m-1",
  name: "ThinkPad T14",
  manufacturer: "Lenovo",
  category_id: null,
  image_url: null,
} as unknown as EquipmentModel;

/**
 * The dictionary lists in this module ended their rows with three icons whose
 * accessible names were "Edit", "Clone", "Delete" — twenty-six times over on
 * the models tab. A screen reader user got twenty-six identical "Delete"s and
 * had to count rows. The asset list two clicks away had the convention right
 * all along ("Select item QA Monitor 001"); it just never reached here.
 */
describe("row actions in the equipment dictionaries", () => {
  it("names the record each action belongs to", () => {
    render(
      <ModelGridCard
        model={model}
        onEdit={vi.fn()}
        onClone={vi.fn()}
        onDelete={vi.fn()}
        isClonePending={false}
        isDeletePending={false}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Edit ThinkPad T14" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Clone ThinkPad T14" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Delete ThinkPad T14" }),
    ).toBeInTheDocument();
  });

  it("drops the row of actions altogether when the reader cannot write", () => {
    render(
      <ModelGridCard
        model={model}
        onEdit={vi.fn()}
        onClone={vi.fn()}
        onDelete={vi.fn()}
        isClonePending={false}
        isDeletePending={false}
        readOnly
      />,
    );

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
