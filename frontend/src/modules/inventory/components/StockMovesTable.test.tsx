import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/utils";
import { StockMovesTable } from "./StockMovesTable";
import type { StockMoveRow } from "@/lib/api/stockMoves";

vi.mock("@/contexts/ModulesContext", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/contexts/ModulesContext")>();
  return {
    ...actual,
    useModules: () => ({ isModuleEnabled: () => true }),
  };
});

vi.mock("@/modules/inventory/moveSourceLink", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/modules/inventory/moveSourceLink")>();
  return {
    ...actual,
    useMoveSourceLink: () => (move: { reference_id?: string | null }) =>
      move.reference_id ? `/warehouse/documents/${move.reference_id}` : null,
  };
});

// The register's answer stands in; what the table does with it is the
// behavior under test.
const registerAnswer: { data: Record<string, string> | undefined } = {
  data: {},
};
vi.mock("@/modules/inventory/hooks/useDocumentNumbers", () => ({
  useDocumentNumbers: () => registerAnswer,
}));

const move = (over: Partial<StockMoveRow>): StockMoveRow =>
  ({
    id: "m-1",
    product_name: "Rye flour",
    quantity: "2",
    uom_symbol: "kg",
    from_location_name: null,
    to_location_name: "Aisle 1",
    lot_name: "L-1",
    user_name: "Keeper",
    completed_at: "2026-09-01T08:00:00Z",
    created_at: "2026-09-01T08:00:00Z",
    reference_type: "document",
    reference_id: "doc-1",
    ...over,
  }) as StockMoveRow;

describe("the SOURCE column names the source, not only its kind", () => {
  it("names a document source with its number", () => {
    registerAnswer.data = { "doc-1": "PZ/2026/001" };
    renderWithProviders(<StockMovesTable moves={[move({})]} />);

    expect(screen.getByText("PZ/2026/001")).toBeInTheDocument();
    expect(screen.queryByText("Document")).not.toBeInTheDocument();
    // The document link measured 79x20 on a phone. The badge inside it is
    // not the target — the anchor around it is, and that is what carries
    // the floor: 44 below `md`, 32 with a pointer.
    const link = screen.getByText("PZ/2026/001").closest("a");
    expect(link?.className).toContain("min-h-11");
    expect(link?.className).toContain("md:min-h-8");
  });

  it("keeps the kind word when the register has not answered", () => {
    registerAnswer.data = {};
    renderWithProviders(<StockMovesTable moves={[move({})]} />);

    expect(screen.getByText("Document")).toBeInTheDocument();
  });

  it("names other kinds as it always did", () => {
    registerAnswer.data = {};
    renderWithProviders(
      <StockMovesTable
        moves={[move({ reference_type: "adjustment", reference_id: "st-1" })]}
      />,
    );

    expect(screen.getByText("Stock take")).toBeInTheDocument();
  });
});

describe("the batch column carries the date of the goods that left", () => {
  it("shows the date under the batch", () => {
    registerAnswer.data = {};
    renderWithProviders(
      <StockMovesTable moves={[move({ expiry_date: "2026-10-25" })]} />,
    );

    expect(screen.getByText("Expires Oct 25, 2026")).toBeInTheDocument();
  });

  it("shows no date for a move without one", () => {
    registerAnswer.data = {};
    renderWithProviders(<StockMovesTable moves={[move({})]} />);

    expect(screen.queryByText(/Expires/)).not.toBeInTheDocument();
  });
});

describe("a location carried with its stock reads as where it went", () => {
  it("routes the row from the path it left to the path it reached", () => {
    registerAnswer.data = {};
    renderWithProviders(
      <StockMovesTable
        moves={[
          move({
            from_location_id: "shelf-a",
            from_location_name: "Shelf A",
            to_location_id: "shelf-a",
            to_location_name: "Shelf A",
            reference_type: "location_relocation",
            reference_id: "reloc-1",
            relocated_location_name: "Cold Storage",
            relocated_from_path: "Main Warehouse",
            relocated_to_path: "Pantry Building",
          }),
        ]}
      />,
    );

    // The shelf is the same on both ends — the location kept its id — so
    // naming it twice would say nothing moved.
    expect(screen.queryByText("Shelf A")).not.toBeInTheDocument();
    expect(screen.getByText("Main Warehouse")).toBeInTheDocument();
    expect(screen.getByText("Pantry Building")).toBeInTheDocument();
    expect(screen.getByText("Moved with Cold Storage")).toBeInTheDocument();
  });
});
