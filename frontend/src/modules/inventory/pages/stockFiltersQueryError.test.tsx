import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { renderWithProviders } from "@/test/utils";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import StockMovesPage from "./StockMovesPage";
import StockLevelsPage from "./StockLevelsPage";
import StockAsOfPage from "./StockAsOfPage";

vi.mock("sonner", () => ({
  toast: { loading: vi.fn(), success: vi.fn(), error: vi.fn() },
}));

/**
 * Each of the three stock screens narrows by location, through a search the
 * server answers. A search that failed used to leave a filter holding only
 * "Any location" — a screen that says the organization has no locations.
 */
function renderPage(ui: React.ReactElement) {
  return renderWithProviders(
    <PageHeaderContext.Provider value={{ data: {}, setHeader: vi.fn() }}>
      {ui}
    </PageHeaderContext.Provider>,
  );
}

/**
 * The screens' own data is answered with an error too -- an explicit one, so
 * nothing goes unmocked -- and only the location list is under test: what
 * counts is whether the filter, once opened, says the search failed instead
 * of offering nothing as if the organization had no locations.
 */
function storagesFail() {
  const boom = () => HttpResponse.json({ detail: "boom" }, { status: 500 });
  server.use(
    http.get("/api/v1/locations", boom),
    http.get("/api/v1/stock-moves", boom),
    http.get("/api/v1/stock-quants", boom),
    http.get("/api/v1/stock-as-of", boom),
  );
}

describe("stock screens — the location filter when the locations did not arrive", () => {
  it("movements: says so with a retry", async () => {
    storagesFail();
    renderPage(<StockMovesPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: /filter/i }),
    );
    await userEvent.click(
      await screen.findByRole("combobox", { name: /location/i }),
    );

    expect(
      (await screen.findAllByRole("button", { name: /try again/i })).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText(/no results/i)).not.toBeInTheDocument();
  });

  it("levels: says so with a retry", async () => {
    storagesFail();
    renderPage(<StockLevelsPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: /filter/i }),
    );
    await userEvent.click(
      await screen.findByRole("combobox", { name: /location/i }),
    );

    expect(
      (await screen.findAllByRole("button", { name: /try again/i })).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText(/no results/i)).not.toBeInTheDocument();
  });

  it("as of: says so with a retry", async () => {
    storagesFail();
    renderPage(<StockAsOfPage />);
    await userEvent.click(
      await screen.findByRole("combobox", { name: /location/i }),
    );

    expect(
      (await screen.findAllByRole("button", { name: /try again/i })).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText(/no results/i)).not.toBeInTheDocument();
  });
});
