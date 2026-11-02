import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "./utils";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import StockLevelsPage from "@/modules/inventory/pages/StockLevelsPage";
import StockLotsPage from "@/modules/inventory/pages/StockLotsPage";
import StockMovesPage from "@/modules/inventory/pages/StockMovesPage";
import PurchaseOrdersPage from "@/modules/purchase_orders/pages/PurchaseOrdersPage";

/**
 * A failed list query has no answer to "how many", and the register bar
 * used to answer anyway — `data?.total ?? 0` reads as zero, so a reader
 * meeting a 500 saw "0 stock entries" over the error card, on the one
 * screen whose whole job is answering whether there is anything at all.
 * The correct shape already existed on the label pool: the count is
 * withheld while the query is failing (`resultCount={isError ? undefined :
 * total}`), because `ListControlBar` renders the number only when the prop
 * is defined.
 *
 * One test per list, each asserting both halves: the error card is on the
 * screen, and the count is not. Without the first half a page that crashed
 * on render would pass the second half for the wrong reason.
 */

const errorResult = {
  data: undefined,
  isLoading: false,
  isError: true,
  error: new Error("boom"),
  refetch: vi.fn(),
};

vi.mock("@/modules/inventory/hooks/useStockQuants", () => ({
  useStockQuants: () => errorResult,
}));

vi.mock("@/modules/inventory/hooks/useStockLots", () => ({
  useStockLots: () => errorResult,
  useSetLotStatus: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@/modules/inventory/hooks/useStockMoves", () => ({
  useStockMoves: () => errorResult,
}));

vi.mock("@/modules/purchase_orders/hooks/usePurchaseOrders", () => ({
  usePurchaseOrders: () => errorResult,
  usePurchaseOrder: () => ({ data: undefined }),
  useConfirmPurchaseOrder: () => ({ mutate: vi.fn(), isPending: false }),
  useCancelPurchaseOrder: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@/modules/purchase_orders/hooks/usePOConfirmMessage", () => ({
  usePOConfirmMessage: () => "Confirm this order?",
}));

function renderPage(page: React.ReactElement) {
  return renderWithProviders(
    <PageHeaderContext.Provider value={{ data: {}, setHeader: vi.fn() }}>
      {page}
    </PageHeaderContext.Provider>,
  );
}

describe("a list in the error state renders no result count", () => {
  it("stock levels: no count over the error card", () => {
    renderPage(<StockLevelsPage />);
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/0 stock entries/)).not.toBeInTheDocument();
  });

  it("lots: no count over the error card", () => {
    renderPage(<StockLotsPage />);
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/0 batches/)).not.toBeInTheDocument();
  });

  it("moves: no count over the error card", () => {
    renderPage(<StockMovesPage />);
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/0 movements/)).not.toBeInTheDocument();
  });

  it("purchase orders: no count over the error card", () => {
    renderPage(<PurchaseOrdersPage />);
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/0 Results/i)).not.toBeInTheDocument();
  });
});
