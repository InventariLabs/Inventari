import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/utils";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { stockValueMovementApi } from "@/modules/inventory/api/stockValueMovement";
import { todayIso } from "@/utils/formatters";
import StockValueMovementPage from "./StockValueMovementPage";

const mocks = vi.hoisted(() => ({
  asked: [] as Record<string, unknown>[],
  downloadBlob: vi.fn(),
  state: {
    data: undefined as unknown,
    isError: false,
    error: undefined as unknown,
  },
}));

const STATEMENT = {
  date_from: "2026-06-01",
  date_to: "2026-06-30",
  generated_at: "2026-07-01T10:00:00Z",
  complete_from: "2026-05-01T00:00:00Z",
  organization_name: "QA Many",
  currency: "USD",
  value_source: "valuation_layers",
  excluded_currency_receipts: 0,
  opening_value: "20.00",
  receipts: "20.00",
  internal_receipts: "0.00",
  used: "-8.00",
  disposed: "-4.00",
  other_issues: "0.00",
  work_in_progress_change: "0.00",
  other_changes: "0.00",
  closing_value: "28.00",
};

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

vi.mock("@/modules/inventory/hooks/useStockValueMovement", () => ({
  useStockValueMovement: (query: Record<string, unknown>) => {
    mocks.asked.push(query);
    return {
      data: mocks.state.isError ? undefined : mocks.state.data,
      isLoading: false,
      isError: mocks.state.isError,
      error: mocks.state.error,
      refetch: vi.fn(),
    };
  },
}));

vi.mock("@/modules/inventory/api/stockValueMovement", () => ({
  stockValueMovementApi: { exportXlsx: vi.fn() },
}));

vi.mock("@/utils/helpers", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/utils/helpers")>();
  return { ...actual, downloadBlob: mocks.downloadBlob };
});

function renderPage() {
  return renderWithProviders(
    <PageHeaderContext.Provider value={{ data: {}, setHeader: vi.fn() }}>
      <StockValueMovementPage />
    </PageHeaderContext.Provider>,
  );
}

describe("StockValueMovementPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.asked.length = 0;
    mocks.state.data = STATEMENT;
    mocks.state.isError = false;
    mocks.state.error = undefined;
  });

  it("opens on the current month and asks for it", () => {
    renderPage();

    const today = todayIso();
    expect(mocks.asked[0]).toEqual({
      date_from: `${today.slice(0, 8)}01`,
      date_to: today,
    });
  });

  it("reads the period as opening, movements and closing", () => {
    renderPage();

    const table = screen.getByRole("table");
    const rows = within(table).getAllByRole("row");
    // header, opening, receipts, used, disposed, closing
    expect(rows).toHaveLength(6);
    expect(within(rows[1]!).getByText(/^Value on /)).toBeInTheDocument();
    expect(within(rows[2]!).getByText("Receipts")).toBeInTheDocument();
    expect(within(rows[3]!).getByText("Used")).toBeInTheDocument();
    expect(within(rows[4]!).getByText("Disposed of")).toBeInTheDocument();
    expect(within(rows[5]!).getByText(/end of the day/)).toBeInTheDocument();
  });

  it("leaves out the lines that hold nothing, and shows the ones that do", () => {
    mocks.state.data = { ...STATEMENT, other_changes: "0.05" };
    renderPage();

    expect(
      screen.queryByText(/^Produced and returned/),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/^Other changes/)).toBeInTheDocument();
  });

  it("explains instead of printing zeros where no cost history is kept", () => {
    mocks.state.data = {
      ...STATEMENT,
      value_source: null,
      opening_value: null,
      closing_value: null,
    };
    renderPage();

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText(/No cost history is kept/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export" })).toBeDisabled();
  });

  it("prints a refusal where the table would be", () => {
    mocks.state.isError = true;
    mocks.state.error = {
      isAxiosError: true,
      response: {
        status: 400,
        data: { detail: { code: "X", message: "Nothing before 12 March." } },
      },
    };
    renderPage();

    expect(screen.getByText("Nothing before 12 March.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("exports the period on screen as a spreadsheet named after it", async () => {
    const blob = new Blob(["x"]);
    vi.mocked(stockValueMovementApi.exportXlsx).mockResolvedValue(blob);
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "Export" }));

    const today = todayIso();
    const first = `${today.slice(0, 8)}01`;
    await waitFor(() =>
      expect(mocks.downloadBlob).toHaveBeenCalledWith(
        blob,
        `value_movement_${first}_${today}.xlsx`,
      ),
    );
    expect(stockValueMovementApi.exportXlsx).toHaveBeenCalledWith({
      date_from: first,
      date_to: today,
    });
  });
});
