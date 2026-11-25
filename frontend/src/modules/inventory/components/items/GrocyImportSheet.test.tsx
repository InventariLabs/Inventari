import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import type { components } from "@/module-sdk";
import { GrocyImportSheet } from "./GrocyImportSheet";

type Analysis = components["schemas"]["GrocyFileAnalysis"];
type Outcome = components["schemas"]["ItemImportResponse"];

const analyzeGrocy = vi.fn();
const mutateAsync = vi.fn();
const toastError = vi.fn();

vi.mock("@/lib/api/items", () => ({
  itemsApi: { analyzeGrocy: (file: File) => analyzeGrocy(file) },
}));

vi.mock("@/modules/inventory/hooks/useItemMutations", () => ({
  useImportGrocy: () => ({ mutateAsync }),
}));

// A seeded category: stored in English, shown by its code's translation.
vi.mock("@/modules/shared/hooks/useCategories", () => ({
  useAllCategories: () => ({
    data: [{ id: "c-dairy", name: "Dairy", code: "dairy" }],
  }),
}));

vi.mock("sonner", () => ({
  toast: { error: (msg: string) => toastError(msg), success: vi.fn() },
}));

const analysis: Analysis = {
  products: 12,
  stock_entries: 30,
  already_imported: 0,
  locations: 3,
  product_groups: 4,
  stores: 2,
  shopping_list_entries: 5,
  new_locations: ["Pantry", "Chest freezer"],
  new_categories: ["Dairy products", "Dairy"],
  new_suppliers: ["Corner shop"],
  currency: "EUR",
  steps: 31,
  left_behind: [
    { what: "recipes", count: 7, names: [] },
    { what: "units_as_pieces", count: 1, names: ["Tin"] },
  ],
};

const outcome: Outcome = {
  total: 31,
  imported: 31,
  joined_existing: 18,
  updated: 0,
  skipped: 0,
  failed: 0,
  errors: [],
  created_locations: ["Pantry", "Chest freezer"],
  created_categories: [],
  created_suppliers: ["Corner shop"],
  left_behind: [{ what: "recipes", count: 7, names: [] }],
  brought_by_modules: [
    {
      module: "shopping_lists",
      sentence: "Shopping lists from Grocy — lists created: 1, entries: 5",
    },
  ],
};

function pick(name = "grocy.db") {
  const input = screen.getByLabelText("Choose grocy.db", {
    selector: "input",
  }) as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File(["x"], name)] } });
}

describe("GrocyImportSheet", () => {
  beforeEach(() => {
    analyzeGrocy.mockReset();
    mutateAsync.mockReset();
    toastError.mockReset();
  });

  it("says where Grocy keeps its file before asking for it", () => {
    render(<GrocyImportSheet onClose={vi.fn()} summary={() => ""} />);

    expect(
      screen.getByRole("heading", { name: "Move in from Grocy" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/one file, grocy\.db/)).toBeInTheDocument();
  });

  it("shows what the file holds, what it would create and what stays, before writing anything", async () => {
    analyzeGrocy.mockResolvedValue(analysis);
    render(<GrocyImportSheet onClose={vi.fn()} summary={() => ""} />);

    pick();

    expect(await screen.findByText("Batches of stock")).toBeInTheDocument();
    expect(screen.getByText("30")).toBeInTheDocument();
    expect(
      screen.getByText("Locations: Pantry, Chest freezer"),
    ).toBeInTheDocument();
    expect(screen.getByText("Suppliers: Corner shop")).toBeInTheDocument();
    // "Dairy" is the category already here; only the other one is created.
    expect(screen.getByText("Categories: Dairy products")).toBeInTheDocument();
    expect(screen.getByText(/Prices are read in EUR/)).toBeInTheDocument();
    expect(screen.getByText("Recipes")).toBeInTheDocument();
    expect(
      screen.getByText("Units counted in pieces: Tin"),
    ).toBeInTheDocument();
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("moves the household and says what it created and what stayed", async () => {
    analyzeGrocy.mockResolvedValue(analysis);
    mutateAsync.mockResolvedValue(outcome);
    render(
      <GrocyImportSheet
        onClose={vi.fn()}
        summary={(result) =>
          `Added ${result.imported - result.joined_existing} products`
        }
      />,
    );
    pick();
    await screen.findByText("Batches of stock");

    await userEvent.click(screen.getByRole("button", { name: /Move in/ }));

    expect(await screen.findByText("Added 13 products")).toBeInTheDocument();
    expect(mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        file: expect.any(File),
        categoryMatches: { Dairy: "c-dairy" },
      }),
    );
    expect(screen.getByText("1 supplier created")).toBeInTheDocument();
    expect(screen.getByText("Corner shop")).toBeInTheDocument();
    expect(screen.getByText("Stays in Grocy")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Shopping lists from Grocy — lists created: 1, entries: 5",
      ),
    ).toBeInTheDocument();
  });

  it("refuses a file that is not Grocy's with the server's reason", async () => {
    analyzeGrocy.mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 400,
        data: {
          detail: {
            code: "GROCY_FILE_UNREADABLE",
            message: "This file is not a database Grocy wrote.",
          },
        },
      },
    });
    render(<GrocyImportSheet onClose={vi.fn()} summary={() => ""} />);

    pick("stock.csv");

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(
        "This file is not a database Grocy wrote.",
      ),
    );
    expect(screen.queryByText("Batches of stock")).not.toBeInTheDocument();
  });
});
