import { beforeEach, describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import UnitConversionsPage from "./UnitConversionsPage";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const conversionsMock = vi.hoisted(() => ({ rows: [] as unknown[] }));

const SYSTEM_ROW = {
  id: "s1",
  lang: "en",
  ingredient_key: "dried_fruit",
  ingredient_name: "Dried fruit",
  source_unit: "cup",
  metric_quantity: 150,
  metric_unit: "g",
  category: "dry",
  is_system: true,
};

const CUSTOM_ROW = {
  id: "c1",
  lang: "en",
  ingredient_key: "my-house-mix",
  ingredient_name: "My house mix",
  source_unit: "tbsp",
  metric_quantity: 12,
  metric_unit: "g",
  category: "dry",
  is_system: false,
};

vi.mock("../hooks/useUnitConversions", () => ({
  useUnitConversions: () => ({ data: conversionsMock.rows, isLoading: false }),
  useCreateUnitConversion: () => ({ mutateAsync: vi.fn() }),
  useUpdateUnitConversion: () => ({ mutateAsync: vi.fn() }),
  useDeleteUnitConversion: () => ({ mutateAsync: vi.fn() }),
}));

describe("UnitConversionsPage — technical keys", () => {
  beforeEach(() => {
    conversionsMock.rows = [SYSTEM_ROW, CUSTOM_ROW];
  });

  it("hides the technical key for system rows, keeps it for custom ones", () => {
    render(<UnitConversionsPage />);
    expect(screen.getByText("Dried fruit")).toBeInTheDocument();
    expect(screen.queryByText(/dried_fruit/)).not.toBeInTheDocument();
    expect(screen.getByText("My house mix")).toBeInTheDocument();
    expect(screen.getByText(/my-house-mix/)).toBeInTheDocument();
  });
});

describe("UnitConversionsPage — the empty table explains itself", () => {
  it("keeps the explanation out of the title", () => {
    conversionsMock.rows = [];
    render(<UnitConversionsPage />);

    const empty = screen.getByTestId("empty-state");
    expect(within(empty).getByText("No conversions found")).toBeInTheDocument();
    expect(
      within(empty).getByText(
        "Add one above, or change the search to see every conversion.",
      ),
    ).toBeInTheDocument();
  });
});
