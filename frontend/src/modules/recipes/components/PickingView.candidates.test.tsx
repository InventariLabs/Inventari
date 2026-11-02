import { http, HttpResponse } from "msw";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import PickingView from "./PickingView";
import { QueryWrapper } from "@/test/queryWrapper";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";

const mockHook = vi.hoisted(() => ({
  state: { phase: "idle" } as unknown,
  isLoading: false,
  error: null as string | null,
  refusals: {} as Record<string, string>,
  startSession: vi.fn(),
  scan: vi.fn(),
  resolveDisambiguation: vi.fn(),
  undoPick: vi.fn(),
  dismissFefoMismatch: vi.fn(),
  dismissOpenedSuggestion: vi.fn(),
  completeSession: vi.fn(),
  cancelSession: vi.fn(),
  reset: vi.fn(),
}));

vi.mock("../hooks/usePickingSession", () => ({
  usePickingSession: () => mockHook,
}));

/**
 * The packs offered when a barcode matches the same product on two shelves.
 * One at 0.75 pcs on a card recording 2 kg a piece read as a bare fraction of
 * a piece; it now says what is left in the product's own unit.
 */
function offer(candidates: Record<string, unknown>[]) {
  server.use(
    http.get("*/uoms/categories", () =>
      HttpResponse.json(
        onePage([
          {
            id: "cat-weight",
            name: "Weight",
            uoms: [
              {
                id: "uom-kg",
                category_id: "cat-weight",
                name: "Kilogram",
                symbol: "kg",
              },
            ],
          },
          {
            id: "cat-unit",
            name: "Unit",
            uoms: [
              {
                id: "uom-pcs",
                category_id: "cat-unit",
                name: "Piece",
                symbol: "pcs",
              },
            ],
          },
        ]),
      ),
    ),
  );
  mockHook.state = {
    phase: "disambiguation",
    session: {
      picking_session_id: "sess-1",
      recipe_name: "Bread",
      servings: 1,
      items_to_pick: [],
    },
    items: [],
    scanResult: {
      status: "disambiguation_required",
      ingredient_name: "Flour",
      candidates,
    },
  };
  render(
    <QueryWrapper>
      <PickingView recipeId="r1" recipeName="Bread" onClose={vi.fn()} />
    </QueryWrapper>,
  );
}

const pack = (quantity: number, extra: Record<string, unknown> = {}) => ({
  item_id: crypto.randomUUID(),
  quantity,
  uom_id: "uom-pcs",
  uom_symbol: "pcs",
  expiry_date: null,
  location: "Pantry",
  recommended: false,
  ...extra,
});

describe("picking candidates — a partly used package", () => {
  it("reads what is left in the product's weight unit", async () => {
    offer([
      pack(0.75, { piece_measure_value: 2, piece_measure_symbol: "kg" }),
      pack(2, { piece_measure_value: 2, piece_measure_symbol: "kg" }),
    ]);

    expect(await screen.findByText("1.5 kg left of 2 kg")).toBeInTheDocument();
    expect(screen.getByText("2 pcs.")).toBeInTheDocument();
  });

  it("keeps the quantity in its unit when the card records no weight", async () => {
    offer([pack(0.75), pack(2)]);

    expect(await screen.findByText("0.75 pcs.")).toBeInTheDocument();
    expect(screen.queryByText(/left of/)).toBeNull();
  });
});

describe("picking candidates — an open pack beside a sealed one", () => {
  const sealed = {
    opened: false,
    expiry_date: "2027-01-10",
    recommended: true,
  };
  const opened = {
    opened: true,
    opened_at: "2026-10-01T09:00:00+00:00",
    expiry_date: "2027-01-31",
  };

  it("marks the open pack and tells the cook the choice is theirs", async () => {
    offer([pack(2, sealed), pack(0.75, opened)]);

    expect(await screen.findByText("Opened")).toBeInTheDocument();
    expect(
      screen.getByText(/an open pack and a sealed one that expires earlier/i),
    ).toBeInTheDocument();
    expect(screen.getByText("2027-01-10")).toBeInTheDocument();
    expect(screen.getByText("2027-01-31")).toBeInTheDocument();
    expect(screen.getByText(/^Opened /)).toBeInTheDocument();
  });

  it("says nothing about a choice when every pack is sealed", async () => {
    offer([pack(2, sealed), pack(3, { opened: false })]);

    expect(await screen.findByText("2 pcs.")).toBeInTheDocument();
    expect(screen.queryByText("Opened")).toBeNull();
    expect(screen.queryByText(/open pack and a sealed one/i)).toBeNull();
  });
});
