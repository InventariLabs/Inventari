import { describe, expect, it, vi, beforeEach } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/utils";
import { RecentStockMoves } from "./RecentStockMoves";

const listSpy = vi.fn();
let page: { items: unknown[]; total: number; next_cursor?: string } = {
  items: [],
  total: 0,
};

const MOVE = {
  id: "m1",
  organization_id: "org",
  product_template_id: "p1",
  from_location_id: "l1",
  to_location_id: null,
  quantity: "4.000",
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
  from_location_name: "Aisle 1",
  to_location_name: null,
  lot_name: null,
  user_name: "Hanna Kowal",
};

vi.mock("@/modules/inventory/hooks/useStockMoves", () => ({
  useStockMoves: (filters: unknown) => {
    listSpy(filters);
    return {
      data: {
        limit: 20,
        offset: 0,
        has_more: Boolean(page.next_cursor),
        next_cursor: null,
        ...page,
      },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    };
  },
}));

function renderPanel(props: Partial<Parameters<typeof RecentStockMoves>[0]>) {
  return renderWithProviders(
    <RecentStockMoves
      filters={{ product_template_id: "p1", location_id: "l1" }}
      caption="Movements of this product in Aisle 1"
      emptyTitle="Nothing moved"
      emptyDescription="Nothing yet."
      {...props}
    />,
  );
}

describe("RecentStockMoves", () => {
  beforeEach(() => {
    listSpy.mockClear();
    page = { items: [MOVE], total: 1 };
  });

  it("asks the ledger only about its own subject", () => {
    renderPanel({});

    expect(listSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        product_template_id: "p1",
        location_id: "l1",
      }),
    );
  });

  it("says what the list is before showing it", () => {
    renderPanel({});

    expect(
      screen.getByText("Movements of this product in Aisle 1"),
    ).toBeInTheDocument();
  });

  it("drops the product column where every row is the same product", () => {
    renderPanel({ showProduct: false });

    const table = screen.getByRole("table");
    expect(
      within(table).queryByRole("columnheader", { name: "Product" }),
    ).not.toBeInTheDocument();
    // The rows are still there -- it is the repetition that goes, not the
    // movement.
    expect(within(table).getByText("Aisle 1")).toBeInTheDocument();
  });

  it("keeps the product column on a subject that is not a product", () => {
    renderPanel({});

    expect(
      screen.getByRole("columnheader", { name: "Product" }),
    ).toBeInTheDocument();
  });

  it("does not offer paging for a history that fits on one page", () => {
    renderPanel({});

    expect(
      screen.queryByRole("button", { name: /next/i }),
    ).not.toBeInTheDocument();
  });

  it("pages a long history by the cursor of the page on screen", async () => {
    page = { items: [MOVE], total: 45, next_cursor: "after-m1" };
    const user = userEvent.setup();
    renderPanel({});

    await user.click(screen.getByRole("button", { name: "Next page" }));

    expect(listSpy).toHaveBeenLastCalledWith(
      expect.objectContaining({ cursor: "after-m1", limit: 20 }),
    );
    expect(listSpy.mock.lastCall?.[0]).not.toHaveProperty("offset");
  });

  it("says its own kind of nothing", () => {
    page = { items: [], total: 0 };
    renderPanel({});

    expect(screen.getByText("Nothing moved")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
