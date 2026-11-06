import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { serveLocations } from "@/test/serveLocations";
import i18n from "@/i18n/config";
import type { StockMoveRow } from "@/lib/api/stockMoves";
import {
  DashboardRecentMoves,
  RECENT_MOVES_LIMIT,
} from "./DashboardRecentMoves";

function move(overrides: Partial<StockMoveRow>): StockMoveRow {
  return {
    id: "m",
    organization_id: "org-1",
    product_template_id: "tpl-1",
    from_location_id: null,
    to_location_id: null,
    quantity: "1.000",
    lot_id: null,
    state: "done",
    reference_type: null,
    reference_id: null,
    created_by: "u1",
    created_at: "2026-09-20T09:00:00Z",
    updated_at: null,
    completed_at: "2026-09-20T09:00:00Z",
    product_name: "Flour",
    uom_symbol: "kg",
    from_location_name: null,
    to_location_name: null,
    lot_name: null,
    user_name: "Ada",
    ...overrides,
  };
}

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider
    client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
  >
    <MemoryRouter>{children}</MemoryRouter>
  </QueryClientProvider>
);

describe("DashboardRecentMoves", () => {
  let requestedLimit: string | null = null;
  let requestedExclusion: string | null = null;

  beforeEach(() => {
    requestedLimit = null;
    requestedExclusion = null;
    server.use(
      http.get("*/stock-moves", ({ request }) => {
        const params = new URL(request.url).searchParams;
        requestedLimit = params.get("limit");
        requestedExclusion = params.get("exclude_module_contexts");
        return HttpResponse.json({
          items: [
            move({
              id: "moved",
              from_location_id: "pantry",
              from_location_name: "Pantry",
              to_location_id: "fridge",
              to_location_name: "Fridge",
              completed_at: "2026-09-21T09:12:00Z",
            }),
            move({
              id: "in",
              product_name: "Orange juice",
              uom_symbol: "pcs",
              quantity: "8.000",
              to_location_id: "fridge",
              to_location_name: "Fridge",
              completed_at: "2026-09-20T06:40:00Z",
            }),
            move({
              id: "out",
              product_name: "UHT milk",
              quantity: "2.000",
              from_location_id: "fridge",
              from_location_name: "Fridge",
              completed_at: "2026-09-19T18:00:00Z",
            }),
          ],
          total: 3,
          offset: 0,
          limit: RECENT_MOVES_LIMIT,
          has_more: false,
        });
      }),
    );
  });

  it("asks the ledger for the last few moves only", async () => {
    render(<DashboardRecentMoves />, { wrapper });
    await screen.findByText("Flour");
    expect(requestedLimit).toBe(String(RECENT_MOVES_LIMIT));
  });

  it("leaves out the moves of module records, like the products list", async () => {
    render(<DashboardRecentMoves />, { wrapper });
    await screen.findByText("Flour");
    expect(requestedExclusion).toBe("true");
  });

  it("shows them again once the organization asks to see module data", async () => {
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({
          id: "org-1",
          name: "Test Org",
          currency: "PLN",
          created_at: "2026-01-01T00:00:00Z",
          created_by: null,
          enabled_modules: ["core", "items"],
          active_profile_id: "food_home",
          settings: { show_module_data: true },
        }),
      ),
    );
    render(<DashboardRecentMoves />, { wrapper });
    await screen.findByText("Flour");
    await waitFor(() => expect(requestedExclusion).toBe("false"));
  });

  it("keeps the ledger's newest-first order, naming product and places", async () => {
    render(<DashboardRecentMoves />, { wrapper });
    // The loading placeholders are list items too; wait for the rows.
    await screen.findByText("Flour");
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("Flour");
    expect(rows[0]).toHaveTextContent("Pantry → Fridge");
    expect(rows[1]).toHaveTextContent("Orange juice");
    expect(rows[1]).toHaveTextContent("Fridge");
    expect(rows[2]).toHaveTextContent("UHT milk");
    expect(rows[2]).toHaveTextContent("Fridge");
    expect(within(rows[0]).getByText("Flour").tagName).toBe("STRONG");
  });

  it("names a place by its path, so two shelves of one name stay two", async () => {
    serveLocations([
      { id: "wa", name: "Warehouse A", parent_id: null },
      { id: "wb", name: "Warehouse B", parent_id: null },
      { id: "shelf-a", name: "Shelf 1", parent_id: "wa" },
      { id: "shelf-b", name: "Shelf 1", parent_id: "wb" },
    ]);
    server.use(
      http.get("*/stock-moves", () =>
        HttpResponse.json({
          items: [
            move({
              id: "between",
              product_name: "Hex Bolt M8",
              quantity: "30.000",
              uom_symbol: "pcs",
              from_location_id: "shelf-a",
              from_location_name: "Shelf 1",
              to_location_id: "shelf-b",
              to_location_name: "Shelf 1",
            }),
          ],
          total: 1,
          offset: 0,
          limit: RECENT_MOVES_LIMIT,
          has_more: false,
        }),
      ),
    );
    render(<DashboardRecentMoves />, { wrapper });
    await screen.findByText("Hex Bolt M8");
    await waitFor(() =>
      expect(screen.getAllByRole("listitem")[0]).toHaveTextContent(
        "Warehouse A › Shelf 1 → Warehouse B › Shelf 1",
      ),
    );
  });

  it("tells a receipt, an issue and a transfer apart in words", async () => {
    render(<DashboardRecentMoves />, { wrapper });
    // The loading placeholders are list items too; wait for the rows.
    await screen.findByText("Flour");
    const rows = screen.getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent(/moved/i);
    expect(rows[1]).toHaveTextContent(/received/i);
    expect(rows[2]).toHaveTextContent(/issued/i);
  });

  it("tells them apart in colour too", async () => {
    render(<DashboardRecentMoves />, { wrapper });
    await screen.findByText("Flour");
    const dots = screen
      .getAllByRole("listitem")
      .map((row) => row.querySelector("[aria-hidden='true']"));
    expect(dots[0]).toHaveClass("bg-blue-600");
    expect(dots[1]).toHaveClass("bg-success-500");
    expect(dots[2]).toHaveClass("bg-amber-500");
  });

  it("dates a move by its completion, or its creation until it has one", async () => {
    server.use(
      http.get("*/stock-moves", () =>
        HttpResponse.json({
          items: [
            move({
              id: "done",
              product_name: "Flour",
              created_at: "2026-09-18T08:00:00Z",
              completed_at: "2026-09-20T09:00:00Z",
            }),
            move({
              id: "open",
              product_name: "Sugar",
              created_at: "2026-09-19T08:00:00Z",
              completed_at: null,
            }),
          ],
          total: 2,
          offset: 0,
          limit: RECENT_MOVES_LIMIT,
          has_more: false,
        }),
      ),
    );
    render(<DashboardRecentMoves />, { wrapper });
    await screen.findByText("Flour");
    const moments = screen
      .getAllByRole("listitem")
      .map((row) => row.querySelector("time")?.getAttribute("datetime"));
    expect(moments).toEqual(["2026-09-20T09:00:00Z", "2026-09-19T08:00:00Z"]);
  });

  it("declines the outside by the end of the sentence it fills", async () => {
    // The journal names where a receipt landed; a row with no named landing
    // gets the destination's word for outside, never the source's.
    server.use(
      http.get("*/stock-moves", () =>
        HttpResponse.json({
          items: [
            move({ id: "nowhere", product_name: "Flour", quantity: "1.000" }),
          ],
          total: 1,
          offset: 0,
          limit: RECENT_MOVES_LIMIT,
          has_more: false,
        }),
      ),
    );
    try {
      await i18n.changeLanguage("pl");
      render(<DashboardRecentMoves />, { wrapper });
      await screen.findByText("Flour");
      const row = screen.getAllByRole("listitem")[0];
      expect(row).toHaveTextContent("przyjęto");
      expect(row).toHaveTextContent("na zewnątrz");
      expect(row).not.toHaveTextContent("z zewnątrz");
    } finally {
      await i18n.changeLanguage("en");
    }
  });

  it("does not call a correction or a put-back a delivery", async () => {
    // A number typed up on the record, and flour returned after cooking,
    // used to read "received" exactly like goods arriving from a supplier.
    server.use(
      http.get("*/stock-moves", () =>
        HttpResponse.json({
          items: [
            move({
              id: "delivered",
              product_name: "Milk",
              to_location_id: "fridge",
              to_location_name: "Fridge",
              reference_type: "document",
            }),
            move({
              id: "corrected",
              product_name: "Eggs",
              to_location_id: "fridge",
              to_location_name: "Fridge",
              reference_type: "item",
            }),
            move({
              id: "cooked",
              product_name: "Flour",
              from_location_id: "pantry",
              from_location_name: "Pantry",
              reference_type: "recipe_picking",
            }),
            move({
              id: "returned",
              product_name: "Sugar",
              to_location_id: "pantry",
              to_location_name: "Pantry",
              reference_type: "recipe_picking",
            }),
          ],
          total: 4,
          offset: 0,
          limit: RECENT_MOVES_LIMIT,
          has_more: false,
        }),
      ),
    );
    render(<DashboardRecentMoves />, { wrapper });
    await screen.findByText("Flour");
    const rows = screen.getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent(/received/i);
    expect(rows[1]).toHaveTextContent(/added/i);
    expect(rows[1]).not.toHaveTextContent(/received/i);
    expect(rows[2]).toHaveTextContent(/used for cooking/i);
    expect(rows[3]).toHaveTextContent(/put back after cooking/i);
    expect(rows[3]).not.toHaveTextContent(/received/i);
  });

  it("links to the full journal", async () => {
    render(<DashboardRecentMoves />, { wrapper });
    await screen.findByText("Flour");
    const links = screen.getAllByRole("link");
    expect(
      links.some((l) => l.getAttribute("href") === "/inventory/moves"),
    ).toBe(true);
  });

  it("points an empty ledger at the stock screen", async () => {
    server.use(
      http.get("*/stock-moves", () =>
        HttpResponse.json({
          items: [],
          total: 0,
          offset: 0,
          limit: RECENT_MOVES_LIMIT,
          has_more: false,
        }),
      ),
    );
    render(<DashboardRecentMoves />, { wrapper });
    expect(await screen.findByText(/no moves yet/i)).toBeInTheDocument();
  });
});
