import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { NutritionTableRow } from "./NutritionTableRow";
import type { IngredientDefault } from "@/modules/recipes/types/nutrition-defaults";

function row(overrides: Partial<IngredientDefault> = {}): IngredientDefault {
  return {
    id: "id-1",
    organization_id: null,
    name: "Flour",
    name_normalized: "flour",
    lang: "en",
    calories_kcal: "350",
    protein_g: "10",
    fat_g: "1",
    carbs_g: "75",
    fiber_g: "3",
    sugar_g: "2",
    salt_g: "0.01",
    source: "system",
    is_system: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

const baseProps = {
  canWrite: true,
  isEditing: false,
  draft: null,
  isPending: false,
  onStartEdit: vi.fn(),
  onCancelEdit: vi.fn(),
  onSaveEdit: vi.fn(),
  onResetOverride: vi.fn(),
  onDraftChange: vi.fn(),
};

describe("NutritionTableRow", () => {
  it("renders kcal as a neutral number, not an orange warning", () => {
    render(<NutritionTableRow {...baseProps} row={row()} />);
    const kcal = screen.getByText("350");
    expect(kcal).not.toHaveClass("text-orange-600");
    expect(kcal).toHaveClass("tabular-nums");
  });

  it("shows the source badge only for custom rows, not for every system row", () => {
    const { rerender } = render(
      <NutritionTableRow {...baseProps} row={row({ is_system: true })} />,
    );
    expect(screen.queryByText("System")).not.toBeInTheDocument();

    rerender(
      <NutritionTableRow {...baseProps} row={row({ is_system: false })} />,
    );
    expect(screen.getByText("Custom")).toBeInTheDocument();
  });
});
