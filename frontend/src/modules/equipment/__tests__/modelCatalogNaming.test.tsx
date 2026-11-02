import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ModelGridCard } from "../components/ModelGridCard";
import ModelEditModal from "../components/ModelEditModal";
import type { EquipmentModel } from "@/modules/equipment/api/equipment";

vi.mock("@/modules/shared/hooks/useCategories", () => ({
  useCategories: () => ({ data: [] }),
  useAllCategories: () => ({ data: [] }),
}));

const model = (overrides: Partial<EquipmentModel> = {}): EquipmentModel =>
  ({
    id: "m1",
    name: "OptiPlex 7010",
    brand: "Dell",
    description: null,
    category_id: null,
    image_url: null,
    equipment_meta: {},
    ...overrides,
  }) as EquipmentModel;

const cardProps = {
  onEdit: vi.fn(),
  onClone: vi.fn(),
  onDelete: vi.fn(),
  isClonePending: false,
  isDeletePending: false,
};

describe("the model catalogue writes the manufacturer once", () => {
  it("keeps the brand when the name does not already carry it", () => {
    render(<ModelGridCard {...cardProps} model={model()} />);

    expect(screen.getByText("Dell OptiPlex 7010")).toBeInTheDocument();
  });

  it("does not glue the brand onto a name that starts with it", () => {
    // 23 of the 39 seeded models carry the manufacturer in the name, because
    // that is the commercial name — "Dell Dell OptiPlex 7010" was the result.
    render(
      <ModelGridCard
        {...cardProps}
        model={model({ name: "Dell OptiPlex 7010" })}
      />,
    );

    expect(screen.getByText("Dell OptiPlex 7010")).toBeInTheDocument();
    expect(screen.queryByText(/Dell Dell/)).toBeNull();
  });

  it("says where the manufacturer goes, so the name is not typed with it", () => {
    render(
      <ModelEditModal
        isOpen
        model={null}
        isSubmitting={false}
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(
      screen.getByText(/manufacturer has its own field/i),
    ).toBeInTheDocument();
  });

  it("does not call a field inside a model 'Model'", () => {
    render(
      <ModelEditModal
        isOpen
        model={null}
        isSubmitting={false}
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Model number")).toBeInTheDocument();
  });
});
