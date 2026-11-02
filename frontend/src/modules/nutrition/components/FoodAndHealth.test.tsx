import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import NutritionSummary from "@/modules/nutrition/components/NutritionSummary";
import ProductInfoDisplay from "@/modules/nutrition/components/ProductInfoDisplay";
import FoodAndHealthExtra from "@/modules/nutrition/components/FoodAndHealthExtra";
import * as modulesCtx from "@/contexts/ModulesContext";
import { withLanguage } from "@/test/mocks/i18n";

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock("@/modules/nutrition/components/NutritionScanner", () => ({
  default: ({ onClose }: { onClose: () => void }) => (
    <div data-testid="nutrition-scanner">
      <button onClick={onClose}>Close Scanner</button>
    </div>
  ),
}));

beforeEach(() => {
  vi.clearAllMocks();
  // The camera route belongs to the vision module; tests run with it on
  // unless a suite says otherwise.
  vi.spyOn(modulesCtx, "useModules").mockReturnValue({
    enabledModules: ["nutrition", "vision"],
    isModuleEnabled: (name: string) => ["nutrition", "vision"].includes(name),
    isLoading: false,
    refreshModules: vi.fn(),
    focusModule: null,
    hiddenModules: [],
  });
});

// ── NutritionSummary ──────────────────────────────────────────────────────────

/** The slot is handed a barcode and the product the scan resolved to. */
const scanned = (metadata: Record<string, unknown>) => ({
  barcode: "590123456789",
  template: { name: "Test", metadata },
});

describe("NutritionSummary", () => {
  it("renders nothing when no nutrition data", () => {
    const { container } = render(<NutritionSummary data={{}} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when nutrition object is empty", () => {
    const { container } = render(
      <NutritionSummary data={scanned({ nutrition: {} })} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders nutrition fields when energy_kcal is set", () => {
    render(
      <NutritionSummary
        data={scanned({ nutrition: { energy_kcal: 200, proteins: 10 } })}
      />,
    );
    expect(screen.getByText("200")).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
  });

  it("renders nutriscore when present", () => {
    render(
      <NutritionSummary
        data={scanned({
          nutrition: { energy_kcal: 100 },
          nutriscore: "a",
        })}
      />,
    );
    // Nutriscore is displayed (uppercase via rendering)
    expect(screen.getByText(/A/)).toBeInTheDocument();
  });

  it("reads the values the scan sheet actually passes it", () => {
    // The scan providers put the item's `meta_data` on the template; nothing
    // in this slot has ever carried an `item`.
    render(
      <NutritionSummary
        data={scanned({ nutrition: { energy_kcal: 350 }, off_enriched: true })}
      />,
    );
    expect(screen.getByText("350")).toBeInTheDocument();
  });
});

// ── ProductInfoDisplay ────────────────────────────────────────────────────────

describe("ProductInfoDisplay", () => {
  it("renders nothing when no data", () => {
    const { container } = render(<ProductInfoDisplay data={{}} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when no food data in metadata", () => {
    const { container } = render(
      <ProductInfoDisplay data={{ formData: { metadata: {} } }} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing for non-food storage type", () => {
    const { container } = render(
      <ProductInfoDisplay
        data={{
          storageTypeCode: "TOOLS",
          formData: {
            metadata: {
              ingredients: "water, sugar",
              nutrition: { energy_kcal: 100 },
            },
          },
        }}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders ingredients when present for food storage", () => {
    render(
      <ProductInfoDisplay
        data={{
          storageTypeCode: "FRIDGE",
          formData: {
            metadata: { ingredients: "water, sugar, salt", nutrition: {} },
          },
        }}
      />,
    );
    expect(screen.getByText(/water, sugar, salt/i)).toBeInTheDocument();
  });

  it("renders nutrition values when present", () => {
    render(
      <ProductInfoDisplay
        data={{
          storageTypeCode: "PANTRY",
          formData: {
            metadata: {
              nutrition: { energy_kcal: 250, proteins: 5 },
            },
          },
        }}
      />,
    );
    expect(screen.getByText("250")).toBeInTheDocument();
  });

  it("shows full ingredients after toggle click", () => {
    const longIngredients = "a".repeat(200);
    render(
      <ProductInfoDisplay
        data={{
          storageTypeCode: "PANTRY",
          formData: {
            metadata: { ingredients: longIngredients, nutrition: {} },
          },
        }}
      />,
    );
    // Find the show-more button and click it
    const buttons = screen.getAllByRole("button");
    if (buttons.length > 0) {
      fireEvent.click(buttons[0]);
      // After click, content should expand
    }
    // The long text should still be rendered
    expect(screen.getByText(longIngredients)).toBeInTheDocument();
  });

  it("renders without storageTypeCode (shows if food data exists)", () => {
    render(
      <ProductInfoDisplay
        data={{
          formData: {
            metadata: { nutrition: { energy_kcal: 180 } },
          },
        }}
      />,
    );
    expect(screen.getByText("180")).toBeInTheDocument();
  });
});

// ── FoodAndHealthExtra ────────────────────────────────────────────────────────

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

describe("FoodAndHealthExtra", () => {
  const foodItem = {
    id: "item-1",
    name: "Apple Juice",
    metadata: {
      nutriscore: "b",
      nutrition: { energy_kcal: 50, proteins: 0.2, fat: 0.1 },
      off_enriched: true,
    },
  };

  it("renders nothing when no item data", () => {
    const { container } = render(<FoodAndHealthExtra data={{}} />, {
      wrapper: createWrapper(),
    });
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing for non-food storage types", () => {
    const { container } = render(
      <FoodAndHealthExtra
        data={{
          item: foodItem as never,
          storageType: { type_code: "TOOLS" },
        }}
      />,
      { wrapper: createWrapper() },
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders nutrition info for food item in fridge", () => {
    render(
      <FoodAndHealthExtra
        data={{
          item: foodItem as never,
          storageType: { type_code: "FRIDGE" },
        }}
      />,
      { wrapper: createWrapper() },
    );
    // Energy value should be rendered
    expect(screen.getByText("50")).toBeInTheDocument();
  });

  it("renders nutriscore badge when valid (A-E)", () => {
    render(
      <FoodAndHealthExtra
        data={{
          item: foodItem as never,
          storageType: { type_code: "PANTRY" },
        }}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText("B")).toBeInTheDocument();
  });

  it("shows scan table button", () => {
    render(
      <FoodAndHealthExtra
        data={{
          item: foodItem as never,
          storageType: { type_code: "FRIDGE" },
        }}
      />,
      { wrapper: createWrapper() },
    );
    // Should have a scan/camera trigger button
    const cameraButtons = screen.getAllByRole("button");
    expect(cameraButtons.length).toBeGreaterThan(0);
  });

  it("opens NutritionScanner on scan button click", () => {
    render(
      <FoodAndHealthExtra
        data={{
          item: foodItem as never,
          storageType: { type_code: "FRIDGE" },
        }}
      />,
      { wrapper: createWrapper() },
    );
    const scanBtn = screen.getAllByRole("button")[0];
    fireEvent.click(scanBtn);
    expect(screen.getByTestId("nutrition-scanner")).toBeInTheDocument();
  });

  it("closes NutritionScanner when onClose called", () => {
    render(
      <FoodAndHealthExtra
        data={{
          item: foodItem as never,
          storageType: { type_code: "FRIDGE" },
        }}
      />,
      { wrapper: createWrapper() },
    );
    const scanBtn = screen.getAllByRole("button")[0];
    fireEvent.click(scanBtn);
    expect(screen.getByTestId("nutrition-scanner")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Close Scanner"));
    expect(screen.queryByTestId("nutrition-scanner")).not.toBeInTheDocument();
  });

  it("renders without storageType restriction (no type = show)", () => {
    render(
      <FoodAndHealthExtra
        data={{
          item: foodItem as never,
        }}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText("50")).toBeInTheDocument();
  });
});

/**
 * All three slots read their figures off the scanned product and printed them
 * with `toLocaleString(undefined, …)` — the browser's locale, not the
 * interface language, so a Polish screen kept a dot in "12.5 g" for anyone
 * whose browser was set to English.
 */
describe("nutrition figures speak the reader's mark", () => {
  it("NutritionSummary writes the gram figure with a comma", async () => {
    await withLanguage("pl", () => {
      render(
        <NutritionSummary
          data={scanned({ nutrition: { energy_kcal: 12.5, proteins: 3.2 } })}
        />,
      );

      expect(screen.getByText("12,5")).toBeInTheDocument();
      expect(screen.getByText("3,2")).toBeInTheDocument();
      expect(screen.queryByText("12.5")).not.toBeInTheDocument();
    });
  });

  it("ProductInfoDisplay writes the gram figure with a comma", async () => {
    await withLanguage("pl", () => {
      render(
        <ProductInfoDisplay
          data={{
            storageTypeCode: "PANTRY",
            formData: { metadata: { nutrition: { energy_kcal: 12.5 } } },
          }}
        />,
      );

      expect(screen.getByText("12,5")).toBeInTheDocument();
      expect(screen.queryByText("12.5")).not.toBeInTheDocument();
    });
  });

  it("FoodAndHealthExtra writes the gram figure with a comma", async () => {
    await withLanguage("pl", () => {
      render(
        <FoodAndHealthExtra
          data={{
            item: {
              id: "item-fr",
              name: "Apple Juice",
              metadata: {
                nutrition: { energy_kcal: 12.5, proteins: 3.2 },
                off_enriched: true,
              },
            } as never,
            storageType: { type_code: "FRIDGE" },
          }}
        />,
        { wrapper: createWrapper() },
      );

      expect(screen.getByText("12,5")).toBeInTheDocument();
      expect(screen.getByText("3,2")).toBeInTheDocument();
      expect(screen.queryByText("12.5")).not.toBeInTheDocument();
    });
  });
});

describe("FoodAndHealthExtra with nothing recorded yet", () => {
  const blankItem = {
    id: "item-2",
    name: "Wheat flour type 550",
    template_id: "tpl-2",
    metadata: {},
  };

  it("lets the values be typed in without having values first", () => {
    render(
      <FoodAndHealthExtra
        data={{
          item: blankItem as never,
          storageType: { type_code: "PANTRY" },
        }}
      />,
      { wrapper: createWrapper() },
    );

    const manual = screen.getByRole("button", {
      name: /enter values by hand/i,
    });
    fireEvent.click(manual);

    expect(
      screen.getByText("Nutritional values per 100 g/ml."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^save$/i })).toBeInTheDocument();
  });

  it("keeps the camera as the only offer when there is nowhere to save", () => {
    // No template means no product to attach the values to.
    render(
      <FoodAndHealthExtra
        data={{
          item: { id: "item-3", name: "Loose apples", metadata: {} } as never,
          storageType: { type_code: "PANTRY" },
        }}
      />,
      { wrapper: createWrapper() },
    );

    expect(
      screen.queryByRole("button", { name: /enter values by hand/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /scan table/i }),
    ).toBeInTheDocument();
  });
});

describe("FoodAndHealthExtra when the vision module is disabled", () => {
  beforeEach(() => {
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: ["nutrition"],
      isModuleEnabled: (name: string) => name === "nutrition",
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
  });

  it("hides the scan entry on a card that already has data", () => {
    render(
      <FoodAndHealthExtra
        data={{
          item: {
            id: "item-4",
            name: "Apple Juice",
            metadata: {
              nutrition: { energy_kcal: 50 },
              off_enriched: true,
            },
          } as never,
          storageType: { type_code: "FRIDGE" },
        }}
      />,
      { wrapper: createWrapper() },
    );

    expect(
      screen.queryByRole("button", { name: /scan table/i }),
    ).not.toBeInTheDocument();
    // The data itself stays — only the camera route is gone.
    expect(screen.getByText("50")).toBeInTheDocument();
  });

  it("hides the scan entry in the empty state", () => {
    render(
      <FoodAndHealthExtra
        data={{
          item: { id: "item-5", name: "Loose apples", metadata: {} } as never,
          storageType: { type_code: "PANTRY" },
        }}
      />,
      { wrapper: createWrapper() },
    );

    expect(
      screen.queryByRole("button", { name: /scan table/i }),
    ).not.toBeInTheDocument();
  });

  it("keeps the manual route when a template exists", () => {
    render(
      <FoodAndHealthExtra
        data={{
          item: {
            id: "item-6",
            name: "Wheat flour type 550",
            template_id: "tpl-6",
            metadata: {},
          } as never,
          storageType: { type_code: "PANTRY" },
        }}
      />,
      { wrapper: createWrapper() },
    );

    expect(
      screen.getByRole("button", { name: /enter values by hand/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /scan table/i }),
    ).not.toBeInTheDocument();
  });
});

// ── Open Food Facts is a community database: say so wherever its figures show ──

describe("community-data note", () => {
  // The scan provider labels its records 'local_off_db'; the importer used
  // the database's own name. Both must carry the note.
  it.each(["local_off_db", "Open Food Facts"])(
    "shows on the scan summary for source %s",
    (source) => {
      render(
        <NutritionSummary
          data={scanned({ source, nutrition: { energy_kcal: 321 } })}
        />,
      );
      expect(screen.getByTestId("community-data-note")).toHaveTextContent(
        /community database.*estimate.*label/i,
      );
    },
  );

  it("shows under the product form's nutrition panel", () => {
    render(
      <ProductInfoDisplay
        data={{
          formData: {
            metadata: {
              source: "local_off_db",
              nutrition: { energy_kcal: 321 },
            },
          },
        }}
      />,
    );
    expect(screen.getByTestId("community-data-note")).toBeInTheDocument();
  });

  it("stays away from figures that were typed in or read from a label", () => {
    render(
      <NutritionSummary
        data={scanned({
          nutrition_source: "vision_capture",
          nutrition: { energy_kcal: 321 },
        })}
      />,
    );
    expect(screen.queryByTestId("community-data-note")).not.toBeInTheDocument();
  });
});
