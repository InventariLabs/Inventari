import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/utils";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { signInWith, signOut } from "@/test/auth";
import StockLotPage from "./StockLotPage";

const navigateSpy = vi.hoisted(() => vi.fn());
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useParams: () => ({ id: "lot-1" }),
    useNavigate: () => navigateSpy,
  };
});

let lot: Record<string, unknown> | undefined = {
  id: "lot-1",
  organization_id: "org",
  product_template_id: "p1",
  name: "L-2026-04",
  is_serial: false,
  expiry_date: "2027-01-31",
  production_date: "2026-04-02",
  use_by_date: null,
  removal_strategy: "FIFO",
  status: "recalled",
  status_reason: "Glass found in jar 12",
  meta_data: null,
  created_at: "2026-04-02T00:00:00Z",
  product_name: "Rye flour",
  uom_symbol: "kg",
  on_hand: "10.000",
  status_history: [],
  locations: [
    {
      location_id: "l1",
      location_name: "Aisle 1",
      quantity: "6.000",
      reserved_quantity: "0",
    },
    {
      location_id: "l2",
      location_name: "Aisle 2",
      quantity: "4.000",
      reserved_quantity: "0",
    },
  ],
};

vi.mock("@/modules/inventory/hooks/useStockLot", () => ({
  useStockLot: () => ({
    data: lot,
    isLoading: false,
    isError: lot === undefined,
    // An axios-shaped 404, or `isNotFoundError` reads the gap as a failure
    // and the screen offers "Try again" over a record that is gone.
    error: { isAxiosError: true, response: { status: 404 } },
    refetch: vi.fn(),
  }),
}));

const mutateAsync = vi.hoisted(() => vi.fn(() => Promise.resolve()));
vi.mock("@/modules/inventory/hooks/useStockLots", () => ({
  useSetLotStatus: () => ({ mutateAsync, isPending: false }),
}));

const movesSpy = vi.fn();
vi.mock("@/modules/inventory/hooks/useStockMoves", () => ({
  useStockMoves: (filters: unknown) => {
    movesSpy(filters);
    return {
      data: { items: [], total: 0, limit: 20, offset: 0, has_more: false },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    };
  },
}));

function renderPage() {
  return renderWithProviders(
    <PageHeaderContext.Provider value={{ data: {}, setHeader: vi.fn() }}>
      <StockLotPage />
    </PageHeaderContext.Provider>,
  );
}

describe("StockLotPage", () => {
  it("says the batch is recalled before it says anything else", () => {
    renderPage();

    // The one fact that decides what the reader does next.
    expect(screen.getByText("Recalled")).toBeInTheDocument();
  });

  it("says why it is recalled, next to the fact that it is", () => {
    renderPage();

    // This is the screen somebody opens on the day of a recall, and
    // "Recalled" without the notice behind it is the half of the answer
    // they did not come for.
    expect(screen.getByText("Glass found in jar 12")).toBeInTheDocument();
  });

  it("says how much is left and on which shelves", () => {
    renderPage();

    expect(screen.getByText("10 kg")).toBeInTheDocument();
    expect(screen.getByText("Aisle 1")).toBeInTheDocument();
    expect(screen.getByText("6 kg")).toBeInTheDocument();
    expect(screen.getByText("Aisle 2")).toBeInTheDocument();
    expect(screen.getByText("4 kg")).toBeInTheDocument();
  });

  it("asks the ledger for this batch and nothing else", () => {
    movesSpy.mockClear();

    renderPage();

    expect(movesSpy).toHaveBeenCalledWith(
      expect.objectContaining({ lot_id: "lot-1" }),
    );
  });

  it("treats a fully shipped batch as a normal end, not a gap", () => {
    lot = { ...(lot as object), on_hand: "0", locations: [] };

    renderPage();

    expect(screen.getByText(/None of this batch is left/)).toBeInTheDocument();
    // The trail is exactly what a recall then asks for, so it stays.
    expect(movesSpy).toHaveBeenCalled();
  });

  it("tells the decisions the batch went through, with who made them", () => {
    lot = {
      ...(lot as object),
      status_history: [
        {
          status: "active",
          reason: "released after the check",
          at: "2026-09-03T10:00:00Z",
          by_name: "Keeper One",
        },
        {
          status: "quarantined",
          reason: "supplier notice 41/26",
          at: "2026-09-01T08:00:00Z",
          by_name: "Keeper Two",
        },
      ],
    };

    renderPage();

    // A quarantine is a decision somebody made for a reason on a day —
    // the movement ledger never held it, so the batch itself says it.
    expect(
      screen.getByText(/The decisions about its state/),
    ).toBeInTheDocument();
    expect(screen.getByText("supplier notice 41/26")).toBeInTheDocument();
    expect(screen.getByText("released after the check")).toBeInTheDocument();
    expect(screen.getByText("Keeper Two")).toBeInTheDocument();
  });

  it("keeps quiet about decisions when there were none", () => {
    lot = { ...(lot as object), status_history: [] };

    renderPage();

    expect(
      screen.queryByText(/The decisions about its state/),
    ).not.toBeInTheDocument();
  });
});

/**
 * The card is where the decision is actually made: the reader has just seen
 * where the batch still lies and what happened to it. The status change used
 * to be one screen away, in the list row's ⋯ menu.
 */
describe("StockLotPage — the decision", () => {
  const setHeader = vi.fn();

  beforeEach(() => {
    mutateAsync.mockClear();
    navigateSpy.mockClear();
    setHeader.mockClear();
    lot = {
      ...(lot as object),
      name: "L-2026-04",
      status: "recalled",
      status_history: [],
    };
    signInWith(["items:read", "items:write"]);
  });

  afterEach(() => signOut());

  /** Renders the page and hands back the actions it put in the shell header. */
  function renderWithHeader(): ReactNode {
    renderWithProviders(
      <PageHeaderContext.Provider value={{ data: {}, setHeader }}>
        <StockLotPage />
      </PageHeaderContext.Provider>,
    );
    const calls = setHeader.mock.calls;
    const last = calls[calls.length - 1]?.[0] as {
      actions?: ReactNode;
    };
    return last.actions;
  }

  // A batch number is chased from a label or an e-mail straight to its card,
  // with no history to go back through. The header's way back then has to
  // lead where the batch is listed, not to the movements ledger.
  it("leads back to the batch list, the way its not-found page does", () => {
    renderWithHeader();
    const calls = setHeader.mock.calls;
    const last = calls[calls.length - 1]?.[0] as { backTo?: string };

    expect(last.backTo).toBe("/inventory/lots");
  });

  it("carries the status actions the list row has", async () => {
    const user = userEvent.setup();
    const actions = renderWithHeader();
    expect(actions).toBeTruthy();
    renderWithProviders(<>{actions}</>);

    await user.click(
      screen.getByRole("button", { name: /Actions for batch L-2026-04/ }),
    );

    expect(screen.getByRole("button", { name: /Release/ })).toBeInTheDocument();
    // The state the batch is already in is not offered, same as the row.
    expect(
      screen.queryByRole("button", { name: /Mark recalled/ }),
    ).not.toBeInTheDocument();
  });

  it("asks why before releasing, and sends the answer from the card", async () => {
    const user = userEvent.setup();
    const actions = renderWithHeader();
    renderWithProviders(<>{actions}</>);

    await user.click(
      screen.getByRole("button", { name: /Actions for batch L-2026-04/ }),
    );
    await user.click(screen.getByRole("button", { name: /Release/ }));

    // Nothing has been sent yet — the dialog is the point.
    expect(mutateAsync).not.toHaveBeenCalled();

    await user.type(
      screen.getByLabelText(/Why/),
      "Supplier withdrew notice 41/26",
    );
    await user.click(screen.getByRole("button", { name: "Change status" }));

    expect(mutateAsync).toHaveBeenCalledWith({
      lotId: "lot-1",
      status: "active",
      reason: "Supplier withdrew notice 41/26",
    });
  });
});

describe("StockLotPage — the exit from a stale link", () => {
  it("leads to the batch list, not the movement ledger", () => {
    const full = lot;
    lot = undefined;
    try {
      renderPage();

      fireEvent.click(screen.getByRole("button", { name: "Back to batches" }));

      expect(navigateSpy).toHaveBeenCalledWith("/inventory/lots");
    } finally {
      lot = full;
    }
  });
});
