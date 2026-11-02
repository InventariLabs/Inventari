import { describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import { renderWithProviders } from "@/test/utils";
import StorageMovesSlot from "./StorageMovesSlot";

let enabledModules: string[] = ["warehouse"];
vi.mock("@/contexts/ModulesContext", async () => {
  const actual = await vi.importActual("@/contexts/ModulesContext");
  return { ...actual, useEnabledModulesOptional: () => enabledModules };
});

const listSpy = vi.fn();
vi.mock("@/modules/inventory/hooks/useStockMoves", () => ({
  useStockMoves: (filters: unknown) => {
    listSpy(filters);
    return {
      data: {
        items: [
          {
            id: "m1",
            organization_id: "org",
            product_template_id: "p1",
            from_location_id: null,
            to_location_id: "loc-1",
            quantity: "6.000",
            lot_id: null,
            state: "done",
            reference_type: "document",
            reference_id: "d1",
            created_by: "u1",
            created_at: "2026-06-20T10:00:00Z",
            updated_at: null,
            completed_at: "2026-06-20T10:00:00Z",
            product_name: "Rye flour",
            uom_symbol: "kg",
            from_location_name: null,
            to_location_name: "Aisle 1",
            lot_name: null,
            user_name: "Hanna Kowal",
          },
        ],
        total: 1,
        limit: 20,
        offset: 0,
        has_more: false,
      },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    };
  },
}));

describe("StorageMovesSlot", () => {
  it("asks what passed through this place, and everything inside it", () => {
    enabledModules = ["warehouse"];
    listSpy.mockClear();

    renderWithProviders(
      <StorageMovesSlot
        data={{ storageId: "loc-1", storageTypeCode: undefined }}
      />,
    );

    // The endpoint answers for the subtree, so a warehouse answers for its
    // own shelves too.
    expect(listSpy).toHaveBeenCalledWith(
      expect.objectContaining({ location_id: "loc-1" }),
    );
    const table = screen.getByRole("table");
    expect(within(table).getByText("Rye flour")).toBeInTheDocument();
  });

  it("adds nothing to the page where nothing records movements", () => {
    enabledModules = ["recipes"];

    const { container } = renderWithProviders(
      <StorageMovesSlot
        data={{ storageId: "loc-1", storageTypeCode: undefined }}
      />,
    );

    // Not an empty state -- a heading over a permanent nothing on every
    // storage page in the organization is worse than no section (ADR-004).
    expect(container).toBeEmptyDOMElement();
  });
});
