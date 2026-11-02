import { describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import { renderWithProviders } from "@/test/utils";
import DocumentMovesSlot from "./DocumentMovesSlot";

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
            from_location_id: "l1",
            to_location_id: null,
            quantity: "8.000",
            lot_id: "lot-1",
            state: "done",
            reference_type: "document",
            reference_id: "doc-1",
            created_by: "u1",
            created_at: "2026-06-20T10:00:00Z",
            updated_at: null,
            completed_at: "2026-06-20T10:00:00Z",
            product_name: "Rye flour",
            uom_symbol: "kg",
            from_location_name: "Aisle 1",
            to_location_name: null,
            lot_name: "L-2026-04",
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

function renderSlot(documentStatus: string) {
  return renderWithProviders(
    <DocumentMovesSlot data={{ documentId: "doc-1", documentStatus }} />,
  );
}

describe("DocumentMovesSlot", () => {
  it("asks only for the movements this document recorded", () => {
    enabledModules = ["warehouse"];
    listSpy.mockClear();

    renderSlot("COMPLETED");

    expect(listSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        reference_type: "document",
        reference_id: "doc-1",
      }),
    );
    // The lines say how much was done; only this says out of which batch.
    const table = screen.getByRole("table");
    expect(within(table).getByText("L-2026-04")).toBeInTheDocument();
    expect(within(table).getByText("8 kg")).toBeInTheDocument();
  });

  it("stays quiet on a document that cannot have moved anything yet", () => {
    enabledModules = ["warehouse"];

    const { container } = renderSlot("DRAFT");

    // "This document moved nothing" is true of every draft ever written --
    // saying it is noise, not information.
    expect(container).toBeEmptyDOMElement();
  });

  it("speaks for a document still being executed", () => {
    enabledModules = ["warehouse"];

    renderSlot("CONFIRMED");

    // Lines are executed one at a time during receiving: the movements are
    // there long before the document reaches COMPLETED.
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("adds nothing where nothing records movements", () => {
    enabledModules = ["recipes"];

    const { container } = renderSlot("COMPLETED");

    expect(container).toBeEmptyDOMElement();
  });
});
