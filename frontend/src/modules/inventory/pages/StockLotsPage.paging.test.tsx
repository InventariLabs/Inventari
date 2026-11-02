import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/utils";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { signInWith, signOut } from "@/test/auth";
import StockLotsPage from "./StockLotsPage";

const mocks = vi.hoisted(() => ({
  asked: [] as { offset: number; limit: number }[],
  refetch: vi.fn(),
  mutateAsync: vi.fn(() => Promise.resolve()),
  failing: false,
}));

const lot = {
  id: "lot-1",
  organization_id: "org",
  product_template_id: "p1",
  name: "L-7",
  is_serial: false,
  expiry_date: null,
  production_date: null,
  use_by_date: null,
  removal_strategy: "FIFO",
  status: "active",
  status_reason: null,
  meta_data: null,
  created_at: "2026-04-02T00:00:00Z",
  product_name: "Rye flour",
  uom_symbol: "kg",
  on_hand: "4.000",
  locations: [],
};

vi.mock("@/modules/inventory/hooks/useStockLots", () => ({
  useStockLots: (filters: { offset: number; limit: number }) => {
    mocks.asked.push(filters);
    return mocks.failing
      ? {
          data: undefined,
          isLoading: false,
          isError: true,
          error: {
            isAxiosError: true,
            response: { status: 500, data: {} },
          },
          refetch: mocks.refetch,
        }
      : {
          data: {
            items: [lot],
            total: 120,
            limit: 50,
            offset: filters.offset,
            has_more: true,
          },
          isLoading: false,
          isError: false,
          error: null,
          refetch: mocks.refetch,
        };
  },
  useSetLotStatus: () => ({ mutateAsync: mocks.mutateAsync, isPending: false }),
}));

function renderPage() {
  return renderWithProviders(
    <PageHeaderContext.Provider value={{ data: {}, setHeader: vi.fn() }}>
      <StockLotsPage />
    </PageHeaderContext.Provider>,
  );
}

const last = () => mocks.asked[mocks.asked.length - 1]!;

/**
 * The batch list a page at a time: the arrows and the typed page move the
 * offset the list asks for, a status dialog can be backed out of without a
 * change being sent, and a server failure offers the retry that asks again.
 */
describe("StockLotsPage — paging, backing out, retrying", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.asked.length = 0;
    mocks.failing = false;
    signInWith(["items:read", "items:write"]);
  });

  afterEach(() => signOut());

  it("asks for the next, previous and typed page", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /next/i }));
    expect(last().offset).toBe(last().limit);
    await user.click(screen.getByRole("button", { name: /previous/i }));
    expect(last().offset).toBe(0);

    const page = screen.getByRole("spinbutton", { name: /page/i });
    await user.clear(page);
    await user.type(page, "3{Enter}");
    expect(last().offset).toBe(2 * last().limit);
  });

  it("sends nothing when the status dialog is cancelled", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(
      screen.getByRole("button", { name: /Actions for batch L-7/ }),
    );
    await user.click(screen.getByRole("button", { name: "Hold" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: /cancel/i }));

    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(mocks.mutateAsync).not.toHaveBeenCalled();
  });

  it("asks again when the list failed", async () => {
    mocks.failing = true;
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /try again|retry/i }));
    expect(mocks.refetch).toHaveBeenCalled();
  });
});
