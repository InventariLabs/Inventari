import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { renderWithProviders } from "@/test/utils";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { stockAsOfApi } from "@/lib/api/stockAsOf";
import { todayIso } from "@/utils/formatters";
import StockAsOfPage from "./StockAsOfPage";

const mocks = vi.hoisted(() => ({
  asked: [] as Record<string, unknown>[],
  refetch: vi.fn(),
  downloadBlob: vi.fn(),
  state: { isError: false, error: undefined as unknown },
}));

const REPORT = {
  as_of: "2026-06-30T23:59:59Z",
  generated_at: "2026-08-29T10:00:00Z",
  complete_from: "2026-05-01T00:00:00Z",
  organization_name: "QA Many",
  currency: "USD",
  value_source: "valuation_layers",
  excluded_currency_rows: 0,
  total_value: "1.00",
  items: [
    {
      product_template_id: "p1",
      product_name: "Rye flour",
      uom_symbol: "kg",
      quantity: "14.000",
      value: "1.00",
    },
  ],
  total: 120,
  limit: 50,
  offset: 0,
  has_more: true,
  unpriced: 0,
};

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

vi.mock("@/modules/inventory/hooks/useStockAsOf", () => ({
  useStockAsOf: (query: Record<string, unknown>) => {
    mocks.asked.push(query);
    return {
      data: mocks.state.isError ? undefined : REPORT,
      isLoading: false,
      isError: mocks.state.isError,
      error: mocks.state.error,
      refetch: mocks.refetch,
    };
  },
}));

vi.mock("@/modules/shared/hooks/useShowInventoryValue", () => ({
  useShowInventoryValue: () => true,
}));

vi.mock("@/lib/api/stockAsOf", () => ({
  stockAsOfApi: { exportXlsx: vi.fn(), exportPdf: vi.fn() },
}));

vi.mock("@/utils/helpers", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/utils/helpers")>();
  return { ...actual, downloadBlob: mocks.downloadBlob };
});

function renderPage() {
  return renderWithProviders(
    <PageHeaderContext.Provider value={{ data: {}, setHeader: vi.fn() }}>
      <StockAsOfPage />
    </PageHeaderContext.Provider>,
  );
}

const last = () => mocks.asked[mocks.asked.length - 1]!;

/**
 * The report's exports and its paging: Export and Print each fetch their own
 * file for the day and place on screen and save it under the day's name; a
 * failed export says so instead of saving nothing; picking another day starts
 * the report from its first page; the page arrows, typed page and page size
 * move the offset; a server failure can be retried.
 */
describe("StockAsOfPage — exports, paging and the retry", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.asked.length = 0;
    mocks.state.isError = false;
    mocks.state.error = undefined;
  });

  it("exports the day on screen as a spreadsheet named after it", async () => {
    const blob = new Blob(["x"]);
    vi.mocked(stockAsOfApi.exportXlsx).mockResolvedValue(blob);
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "Export" }));

    await waitFor(() =>
      expect(mocks.downloadBlob).toHaveBeenCalledWith(
        blob,
        `stock_${todayIso()}.xlsx`,
      ),
    );
    const query = vi.mocked(stockAsOfApi.exportXlsx).mock.calls[0]?.[0];
    expect(query).toMatchObject({ location_id: undefined });
    expect(query?.as_of).toEqual(expect.any(String));
    expect(toast.success).toHaveBeenCalledWith("Export complete", {
      id: "as-of-export",
    });
  });

  it("prints through the PDF export", async () => {
    vi.mocked(stockAsOfApi.exportPdf).mockResolvedValue(new Blob(["%PDF"]));
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "Print" }));

    await waitFor(() =>
      expect(mocks.downloadBlob).toHaveBeenCalledWith(
        expect.any(Blob),
        `stock_${todayIso()}.pdf`,
      ),
    );
    expect(stockAsOfApi.exportXlsx).not.toHaveBeenCalled();
  });

  it("says so when an export fails, and saves nothing", async () => {
    vi.mocked(stockAsOfApi.exportXlsx).mockRejectedValue(new Error("x"));
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "Export" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Export failed", {
        id: "as-of-export",
      }),
    );
    expect(mocks.downloadBlob).not.toHaveBeenCalled();
  });

  it("moves through the pages and back to the first on another day", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /next/i }));
    expect(last()).toMatchObject({ offset: 50 });
    await user.click(screen.getByRole("button", { name: /previous/i }));
    expect(last()).toMatchObject({ offset: 0 });

    const page = screen.getByRole("spinbutton", { name: /page/i });
    await user.clear(page);
    await user.type(page, "3{Enter}");
    expect(last()).toMatchObject({ offset: 100 });

    await user.click(screen.getByRole("combobox", { name: "As of" }));
    await user.click(screen.getByRole("button", { name: "Yesterday" }));
    expect(last()).toMatchObject({ offset: 0 });
    expect(last().as_of).not.toEqual(mocks.asked[0]?.as_of);
  });

  it("starts a new page size from the first page", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /next/i }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: /rows per page/i }),
      "100",
    );

    expect(last()).toMatchObject({ limit: 100, offset: 0 });
  });

  it("asks again when the server failed", async () => {
    mocks.state.isError = true;
    mocks.state.error = {
      isAxiosError: true,
      response: { status: 500, data: {} },
    };
    const user = userEvent.setup();
    renderPage();

    await user.click(within(screen.getByRole("alert")).getByRole("button"));
    expect(mocks.refetch).toHaveBeenCalled();
  });
});
