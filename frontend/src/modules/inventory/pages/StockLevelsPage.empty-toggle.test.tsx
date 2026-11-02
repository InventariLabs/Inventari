import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/utils";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import StockLevelsPage from "./StockLevelsPage";

/**
 * The empty state used to send a reader who asked "which storages are
 * empty" to the include-empty toggle — and the toggle could not answer:
 * `include_empty` only un-hides rows whose quantity was drained to zero,
 * while a storage that never held the product has no row at all. So the
 * label names what the flag really shows (storages at zero for the current
 * filters) and a hint underneath says both halves: what appears, and what
 * cannot.
 */

const listSpy = vi.fn();

vi.mock("@/modules/inventory/hooks/useStockQuants", () => ({
  useStockQuants: (filters: unknown) => {
    listSpy(filters);
    return {
      data: { items: [], total: 0, limit: 50, offset: 0, has_more: false },
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
      <StockLevelsPage />
    </PageHeaderContext.Provider>,
  );
}

describe("the include-empty toggle says what it really does", () => {
  it("the filters panel carries the hint that names the zero rows", async () => {
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: /filter/i }));

    expect(screen.getByText(/quantity is zero/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/^Include empty storages$/),
    ).not.toBeInTheDocument();
  });
});
