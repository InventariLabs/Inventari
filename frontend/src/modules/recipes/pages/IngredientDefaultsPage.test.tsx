import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { signInWith } from "@/test/auth";
import IngredientDefaultsPage from "./IngredientDefaultsPage";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: ["vision", "nutrition"],
    isModuleEnabled: () => true,
  }),
}));

vi.mock("@/modules/recipes/hooks/useIngredientDefaults", () => ({
  useIngredientDefaultsList: () => ({
    data: {
      items: [
        {
          id: "d1",
          organization_id: null,
          name: "Almonds",
          name_normalized: "almonds",
          lang: "en",
          calories_kcal: "579",
          protein_g: "21.2",
          fat_g: "49.9",
          carbs_g: "21.6",
          fiber_g: "12.5",
          sugar_g: "4.4",
          salt_g: null,
          source: "seed",
          is_system: true,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ],
      total: 1,
    },
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  }),
  useCreateIngredientDefault: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useDeleteIngredientDefault: () => ({ mutateAsync: vi.fn() }),
  useImportIngredientDefaults: () => ({ mutateAsync: vi.fn() }),
}));

vi.mock("@/modules/recipes/api/recipes", () => ({
  recipesApi: { exportIngredientDefaults: vi.fn() },
}));

describe("IngredientDefaultsPage — a read-only account", () => {
  beforeEach(() => {
    signInWith(["recipes:read"]);
  });

  it("is not offered the override form, the import, or the row's writes", () => {
    render(<IngredientDefaultsPage />);

    // Reading the dictionary is what the account may do.
    expect(screen.getByText("Almonds")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /add override/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/import csv\/json/i)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: /edit \(overrides only for your organization\)/i,
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/you can view this, not change it/i),
    ).toBeInTheDocument();
  });
});

describe("IngredientDefaultsPage — an account that may write", () => {
  beforeEach(() => {
    signInWith(["recipes:read", "recipes:write"]);
  });

  it("keeps the toolbar and the row's write controls", () => {
    render(<IngredientDefaultsPage />);

    expect(
      screen.getByRole("button", { name: /add override/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/import csv\/json/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: /edit \(overrides only for your organization\)/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/you can view this, not change it/i),
    ).not.toBeInTheDocument();
  });
});

describe("IngredientDefaultsPage — reading a nutrition table off a label", () => {
  async function openTheAddForm() {
    render(<IngredientDefaultsPage />);
    await userEvent.click(
      screen.getByRole("button", { name: /add override/i }),
    );
  }

  it("is offered to an account that may read photographs", async () => {
    signInWith(["recipes:read", "recipes:write", "vision:extract"]);
    await openTheAddForm();

    expect(
      screen.getByRole("button", { name: /read from a label/i }),
    ).toBeInTheDocument();
  });

  it("is not offered without the photograph reader's permission", async () => {
    signInWith(["recipes:read", "recipes:write"]);
    await openTheAddForm();

    expect(
      screen.queryByRole("button", { name: /read from a label/i }),
    ).not.toBeInTheDocument();
  });
});
