import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/utils";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import StockLotsPage from "./StockLotsPage";
import { signInWith, signOut } from "@/test/auth";

const listSpy = vi.fn();
const mutateAsync = vi.hoisted(() => vi.fn(() => Promise.resolve()));

const LOTS = [
  {
    id: "lot-1",
    organization_id: "org",
    product_template_id: "p1",
    name: "L-BAD",
    is_serial: false,
    expiry_date: "2027-01-31",
    production_date: null,
    use_by_date: null,
    removal_strategy: "FIFO",
    status: "recalled",
    status_reason: "Glass found in jar 12",
    meta_data: null,
    created_at: "2026-04-02T00:00:00Z",
    product_name: "Rye flour",
    uom_symbol: "kg",
    on_hand: "4.000",
    locations: [],
  },
];

/** The rows the mocked hook serves; a test points it at [] for emptiness. */
let lots: typeof LOTS = [];

vi.mock("@/modules/inventory/hooks/useStockLots", () => ({
  useStockLots: (filters: unknown) => {
    listSpy(filters);
    return {
      data: {
        items: lots,
        total: lots.length,
        limit: 50,
        offset: 0,
        has_more: false,
      },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    };
  },
  useSetLotStatus: () => ({ mutateAsync, isPending: false }),
}));

function renderPage() {
  return renderWithProviders(
    <PageHeaderContext.Provider value={{ data: {}, setHeader: vi.fn() }}>
      <StockLotsPage />
    </PageHeaderContext.Provider>,
  );
}

describe("StockLotsPage", () => {
  beforeEach(() => {
    listSpy.mockClear();
    mutateAsync.mockClear();
    lots = LOTS;
    // Holding a batch back is `items:write`; without it the ⋯ menu is gone
    // and these tests would be describing the read-only screen.
    signInWith(["items:read", "items:write"]);
  });

  afterEach(() => signOut());

  it("shows a recalled batch with the state that blocks it", () => {
    renderPage();

    const table = screen.getByRole("table");
    expect(within(table).getByText("L-BAD")).toBeInTheDocument();
    expect(within(table).getByText("Recalled")).toBeInTheDocument();
    expect(within(table).getByText("4 kg")).toBeInTheDocument();
  });

  it("under a status filter, the empty state speaks of the filter", async () => {
    lots = [];
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("tab", { name: "Expired" }));

    // A shelf full of batches with an empty Expired tab is the filter's
    // answer, not the receiving process's — the "goods are received" hint
    // would send the reader chasing a delivery that happened.
    expect(screen.getByText("No batch is in this state")).toBeInTheDocument();
    expect(
      screen.queryByText(/batches appear when goods are received/i),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/nothing matches this status/i),
    ).toBeInTheDocument();
  });

  it("with no filter on, the empty state explains where batches come from", () => {
    lots = [];
    renderPage();

    expect(screen.getByText("No batches yet")).toBeInTheDocument();
    expect(
      screen.getByText(/batches appear when goods are received/i),
    ).toBeInTheDocument();
    lots = LOTS;
  });

  it("asks for one state at a time when the reader picks one", async () => {
    const user = userEvent.setup();
    renderPage();
    listSpy.mockClear();

    await user.click(screen.getByRole("tab", { name: "Quarantined" }));

    // On a recall day the question is "what is held back", not "what
    // batches exist".
    expect(listSpy).toHaveBeenCalledWith(
      expect.objectContaining({ status: "quarantined" }),
    );
  });

  it("shows why the batch is held, beside the state that holds it", () => {
    renderPage();

    // A status on its own says a decision was made. The row has to say
    // which one, or the column only records that somebody clicked.
    expect(screen.getByText("Glass found in jar 12")).toBeInTheDocument();
  });

  it("asks why before releasing, and sends the answer", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(
      screen.getByRole("button", { name: /Actions for batch L-BAD/ }),
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

  it("will not let the status change on an empty reason", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(
      screen.getByRole("button", { name: /Actions for batch L-BAD/ }),
    );
    await user.click(screen.getByRole("button", { name: /Release/ }));

    const confirm = screen.getByRole("button", { name: "Change status" });
    expect(confirm).toBeDisabled();

    // Spaces are not an answer either.
    await user.type(screen.getByLabelText(/Why/), "   ");
    expect(confirm).toBeDisabled();
  });

  it("does not offer the state the batch is already in", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(
      screen.getByRole("button", { name: /Actions for batch L-BAD/ }),
    );

    expect(
      screen.queryByRole("button", { name: /Mark recalled/ }),
    ).not.toBeInTheDocument();
  });

  it("leads to the batch's own trail", () => {
    renderPage();

    expect(screen.getByRole("link", { name: "L-BAD" })).toHaveAttribute(
      "href",
      "/inventory/lots/lot-1",
    );
  });
});

/**
 * A reader is told why the batches carry no actions.
 *
 * Every status change on this screen is `PATCH /stock-lots/{id}`, which asks
 * for `items:write`. Without the notice the ⋯ column simply vanishes, and a
 * vanished control reads as a broken page rather than as a boundary.
 */
describe("StockLotsPage — an account that may not change a status", () => {
  beforeEach(() => {
    listSpy.mockClear();
    mutateAsync.mockClear();
    signInWith(["items:read"]);
  });

  afterEach(() => signOut());

  it("says why, and offers no way to change the status", () => {
    renderPage();

    expect(
      screen.getByText(/you can view this, not change it/i),
    ).toBeInTheDocument();
    expect(screen.getByText("L-BAD")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /actions for/i }),
    ).not.toBeInTheDocument();
  });
});
