import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import StockTakeReportPage from "./StockTakeReportPage";
import { withLanguage } from "@/test/mocks/i18n";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";

import * as modulesCtx from "@/contexts/ModulesContext";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mockSetHeader = vi.fn();

const mockReport = {
  stock_take_id: "st-1",
  stock_take_name: "Monthly Check",
  location_name: "Kitchen",
  status: "completed",
  started_at: "2026-08-13T10:00:00Z",
  completed_at: "2026-08-13T10:30:00Z",
  total_items: 4,
  counted_items: 4,
  discrepancies: 2,
  progress_percent: 100,
  perfect_matches: 2,
  overstock: 1,
  understock: 1,
  tolerated_differences: 1,
  not_counted: 0,
  closed_locations: [] as Record<string, unknown>[],
  all_items: [
    {
      id: "sti-1",
      item_name: "Milk",
      system_quantity: 4,
      counted_quantity: 7,
      difference: 3,
      shelf_location: "A-1-01",
      notes: null,
      is_discrepancy: 1,
    },
    {
      id: "sti-2",
      item_name: "Butter",
      system_quantity: 5,
      counted_quantity: 3,
      difference: -2,
      shelf_location: null,
      notes: null,
      is_discrepancy: 1,
    },
    {
      id: "sti-3",
      item_name: "Bread",
      system_quantity: 2,
      counted_quantity: 2,
      difference: 0,
      shelf_location: null,
      notes: null,
      is_discrepancy: 0,
    },
    {
      id: "sti-4",
      item_name: "Eggs",
      system_quantity: 10,
      counted_quantity: 10,
      difference: 0,
      shelf_location: null,
      notes: null,
      is_discrepancy: 0,
    },
    {
      id: "sti-5",
      item_name: "Bananas",
      system_quantity: 2.3,
      counted_quantity: 2.1,
      difference: -0.2,
      shelf_location: null,
      notes: null,
      is_discrepancy: 0,
      uom_symbol: "kg",
    },
  ],
  discrepancy_items: [
    {
      id: "sti-2",
      item_name: "Butter",
      system_quantity: 5,
      counted_quantity: 3,
      difference: -2,
      shelf_location: null,
      notes: null,
      is_discrepancy: 1,
    },
    {
      id: "sti-1",
      item_name: "Milk",
      system_quantity: 4,
      counted_quantity: 7,
      difference: 3,
      shelf_location: "A-1-01",
      notes: null,
      is_discrepancy: 1,
    },
  ],
  tolerated_items: [
    {
      id: "sti-5",
      item_name: "Bananas",
      system_quantity: 2.3,
      counted_quantity: 2.1,
      difference: -0.2,
      shelf_location: null,
      notes: null,
      is_discrepancy: 0,
      uom_symbol: "kg",
    },
  ],
  started_by_name: "QA Many User",
};

let queryClient: QueryClient;

function Wrapper({ children }: { children: ReactNode }) {
  return (
    <PageHeaderContext.Provider value={{ data: {}, setHeader: mockSetHeader }}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </PageHeaderContext.Provider>
  );
}

describe("StockTakeReportPage", () => {
  beforeEach(() => {
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: ["stock_takes"],
      isModuleEnabled: (name: string) => name === "stock_takes",
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mockSetHeader.mockClear();
    server.use(
      http.get("/api/v1/stock-takes/st-1/report", () =>
        HttpResponse.json(mockReport),
      ),
    );
  });

  const renderPage = () =>
    render(
      <MemoryRouter initialEntries={["/inventory/stock-takes/st-1/report"]}>
        <Routes>
          <Route
            path="/inventory/stock-takes/:id/report"
            element={
              <Wrapper>
                <StockTakeReportPage />
              </Wrapper>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

  it("links the stock adjustment the differences posted as", async () => {
    server.use(
      http.get("/api/v1/stock-takes/st-1/report", () =>
        HttpResponse.json({
          ...mockReport,
          adjustment_document_id: "doc-9",
          adjustment_document_number: "ADJ/2026/0007",
        }),
      ),
    );
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: ["stock_takes", "warehouse"],
      isModuleEnabled: () => true,
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
    renderPage();

    const link = await screen.findByRole("link", { name: "ADJ/2026/0007" });
    expect(link).toHaveAttribute("href", "/warehouse/documents/doc-9");
    expect(
      screen.getByText(/The differences were posted as stock adjustment/),
    ).toBeInTheDocument();
  });

  it("says a count that matched everywhere changed nothing", async () => {
    server.use(
      http.get("/api/v1/stock-takes/st-1/report", () =>
        HttpResponse.json({
          ...mockReport,
          counted_items: 2,
          perfect_matches: 2,
          overstock: 0,
          understock: 0,
          tolerated_differences: 0,
          discrepancies: 0,
          all_items: mockReport.all_items.filter((row) => !row.difference),
        }),
      ),
    );
    renderPage();

    expect(
      await screen.findByText(
        "Counted, no differences: the stock was already right.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /ADJ/ })).not.toBeInTheDocument();
  });

  it("renders the summary numbers", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Perfect matches")).toBeInTheDocument();
    });
    // Summary cards: 2 matches / 1 within tolerance / 1 overstock /
    // 1 understock / 0 not counted.
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getAllByText("1")).toHaveLength(3);
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.getByText("Within tolerance")).toBeInTheDocument();
    expect(screen.getByText("30 min")).toBeInTheDocument();
  });

  it("writes the understock count with the warning text token, like its neighbours", async () => {
    // text-amber-600 on the white card was ~3.7:1 at this size.
    renderPage();
    const label = await screen.findByText("Understock");
    const value = label.parentElement?.querySelector("p:nth-of-type(2)");
    expect(value).toHaveClass("text-on-warning");
    expect(value?.className).not.toContain("amber-600");
  });

  it("writes the overstock count in the tone of a surplus line, which has a dark value", async () => {
    // text-primary-700 has no dark variant: 2.97:1 on the dark card.
    renderPage();
    const label = await screen.findByText("Overstock");
    const value = label.parentElement?.querySelector("p:nth-of-type(2)");
    expect(value).toHaveClass("text-on-info");
    expect(value?.className).not.toContain("primary-700");
  });

  it("does not colour a surplus as an error beside an amber shortfall", async () => {
    renderPage();
    await screen.findByText("Milk");
    const surplus = screen.getByText(/^\+3\b/);
    const shortfall = screen.getByText(/^-2\b/);
    expect(surplus).toHaveClass("text-on-info");
    expect(surplus.className).not.toContain("danger");
    expect(shortfall).toHaveClass("text-on-warning");
  });

  it("shows discrepancies by default, sorted by absolute difference desc", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Milk")).toBeInTheDocument();
    });
    const bodyText = document.body.textContent ?? "";
    expect(bodyText.indexOf("Milk")).toBeLessThan(bodyText.indexOf("Butter"));
    // A difference the tolerance accepted is not a perfect match and does
    // not vanish: it shows here, named as what it is.
    expect(screen.getByText("Bananas")).toBeInTheDocument();
    expect(
      screen.getAllByText(/Within tolerance/).length,
    ).toBeGreaterThanOrEqual(2);
    // Matching items stay collapsed.
    expect(screen.queryByText("Bread")).not.toBeInTheDocument();
    expect(screen.queryByText("Eggs")).not.toBeInTheDocument();
  });

  it("says whether the second look at a row agreed with the first", async () => {
    // A recount that confirms the first number is the strongest thing a
    // report can say; one that contradicts it is worth knowing before the
    // figure is trusted.
    const [milk, butter] = mockReport.discrepancy_items;
    server.use(
      http.get("/api/v1/stock-takes/st-1/report", () =>
        HttpResponse.json({
          ...mockReport,
          discrepancy_items: [
            {
              ...butter,
              counts: [
                { sequence: 1, quantity: 3 },
                { sequence: 2, quantity: 3 },
              ],
            },
            {
              ...milk,
              counts: [
                { sequence: 1, quantity: 5 },
                { sequence: 2, quantity: 7 },
              ],
            },
          ],
        }),
      ),
    );
    renderPage();

    expect(
      await screen.findByText("Counted twice, both times 3"),
    ).toBeVisible();
    expect(screen.getByText("Counted twice: 5, then 7")).toBeVisible();
  });

  it("reveals matching items after toggling show all", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Milk")).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: "Show all items" }));
    expect(screen.getByText("Bread")).toBeInTheDocument();
    expect(screen.getByText("Eggs")).toBeInTheDocument();
    // The default view holds differences and uncounted lines, so the way
    // back to it is named for both.
    expect(
      screen.getByRole("button", {
        name: "Show differences and uncounted only",
      }),
    ).toBeInTheDocument();
  });

  it("names the line nobody counted instead of claiming a match", async () => {
    // The empty-differences branch read "every item matched" beside a
    // "Not counted 1" card: the only line had never been counted at all.
    server.use(
      http.get("/api/v1/stock-takes/st-1/report", () =>
        HttpResponse.json({
          ...mockReport,
          total_items: 1,
          counted_items: 0,
          discrepancies: 0,
          progress_percent: 0,
          perfect_matches: 0,
          overstock: 0,
          understock: 0,
          tolerated_differences: 0,
          not_counted: 1,
          all_items: [
            {
              id: "sti-1",
              item_name: "Milk",
              system_quantity: 4,
              counted_quantity: null,
              difference: null,
              shelf_location: null,
              notes: null,
              is_discrepancy: 0,
            },
          ],
          discrepancy_items: [],
          tolerated_items: [],
        }),
      ),
    );

    renderPage();

    expect(await screen.findByText("Milk")).toBeInTheDocument();
    expect(
      screen.queryByText("No discrepancies — every item matched."),
    ).not.toBeInTheDocument();
    // Named for what it is: the card says "Not counted", the row says it too.
    expect(screen.getAllByText("Not counted").length).toBeGreaterThanOrEqual(2);
  });

  it("lists the locations closed, the empty ones as such, and who closed them", async () => {
    server.use(
      http.get("/api/v1/stock-takes/st-1/report", () =>
        HttpResponse.json({
          ...mockReport,
          closed_locations: [
            {
              location_id: "shelf-1",
              path: "Kitchen / Shelf 1",
              empty: false,
              closed_by_name: "Ann Counter",
              closed_at: "2026-08-13T10:20:00Z",
            },
            {
              location_id: "shelf-2",
              path: "Kitchen / Shelf 2",
              empty: true,
              closed_by_name: "Bo Counter",
              closed_at: "2026-08-13T10:25:00Z",
            },
          ],
        }),
      ),
    );
    renderPage();

    const section = (await screen.findByText("Closed locations")).closest(
      "div",
    )!;
    const [counted, empty] = within(section).getAllByRole("listitem");
    expect(counted).toHaveTextContent("Kitchen / Shelf 1");
    expect(counted).toHaveTextContent("Closed");
    expect(counted).toHaveTextContent("Ann Counter");
    expect(empty).toHaveTextContent("Kitchen / Shelf 2");
    expect(empty).toHaveTextContent("Empty");
    expect(empty).toHaveTextContent("Bo Counter");
  });

  it("does not claim a match for a take that holds no lines", async () => {
    server.use(
      http.get("/api/v1/stock-takes/st-1/report", () =>
        HttpResponse.json({
          ...mockReport,
          total_items: 0,
          counted_items: 0,
          discrepancies: 0,
          progress_percent: 0,
          perfect_matches: 0,
          overstock: 0,
          understock: 0,
          tolerated_differences: 0,
          not_counted: 0,
          all_items: [],
          discrepancy_items: [],
          tolerated_items: [],
        }),
      ),
    );

    renderPage();

    expect(
      await screen.findByText("No items in this stock take."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("No discrepancies — every item matched."),
    ).not.toBeInTheDocument();
  });

  it("still calls a fully counted, matching take a match", async () => {
    server.use(
      http.get("/api/v1/stock-takes/st-1/report", () =>
        HttpResponse.json({
          ...mockReport,
          total_items: 2,
          counted_items: 2,
          discrepancies: 0,
          perfect_matches: 2,
          overstock: 0,
          understock: 0,
          tolerated_differences: 0,
          not_counted: 0,
          all_items: [
            {
              id: "sti-1",
              item_name: "Milk",
              system_quantity: 4,
              counted_quantity: 4,
              difference: 0,
              shelf_location: null,
              notes: null,
              is_discrepancy: 0,
            },
            {
              id: "sti-2",
              item_name: "Butter",
              system_quantity: 5,
              counted_quantity: 5,
              difference: 0,
              shelf_location: null,
              notes: null,
              is_discrepancy: 0,
            },
          ],
          discrepancy_items: [],
          tolerated_items: [],
        }),
      ),
    );

    renderPage();

    expect(
      await screen.findByText("No discrepancies — every item matched."),
    ).toBeInTheDocument();
  });

  it("calls a failed request a failure, not a missing stock take", async () => {
    server.use(
      http.get(
        "/api/v1/stock-takes/st-1/report",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    renderPage();

    expect(await screen.findByText("An error occurred")).toBeInTheDocument();
    expect(screen.queryByText("Stock take not found")).not.toBeInTheDocument();
  });

  it("keeps a way back when there is no report to show", async () => {
    // The header used to be emptied whenever the report was missing, so this
    // screen offered no title, no arrow and nothing at all to press.
    server.use(
      http.get(
        "/api/v1/stock-takes/st-1/report",
        () => new HttpResponse(null, { status: 404 }),
      ),
    );

    renderPage();

    await waitFor(() =>
      expect(mockSetHeader).toHaveBeenCalledWith(
        expect.objectContaining({ backTo: "/inventory/stock-takes" }),
      ),
    );
  });
});

describe("StockTakeReportPage — quantities carry their unit, the file its proof", () => {
  beforeEach(() => {
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: ["stock_takes"],
      isModuleEnabled: (name: string) => name === "stock_takes",
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mockSetHeader.mockClear();
    server.use(
      http.get("/api/v1/stock-takes/st-1/report", () =>
        HttpResponse.json(mockReport),
      ),
    );
  });

  const renderPage = () =>
    render(
      <MemoryRouter initialEntries={["/inventory/stock-takes/st-1/report"]}>
        <Routes>
          <Route
            path="/inventory/stock-takes/:id/report"
            element={
              <Wrapper>
                <StockTakeReportPage />
              </Wrapper>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

  /**
   * The weighed row's quantities went through the raw-string trimmer, which
   * strips padding but knows no language: "2.3" on a Polish screen.
   */
  it("writes the quantities with the language's decimal mark", async () => {
    await withLanguage("pl", async () => {
      renderPage();
      await waitFor(() => {
        expect(screen.getByText("Bananas")).toBeInTheDocument();
      });

      expect(screen.getByText("2,3 kg")).toBeInTheDocument();
      expect(screen.getByText("2,1 kg")).toBeInTheDocument();
      expect(screen.queryByText("2.3 kg")).not.toBeInTheDocument();
    });
  });

  it("prints the unit the counting card showed next to every quantity", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Bananas")).toBeInTheDocument();
    });
    // The weighed row reads as kilograms, as it did while being typed.
    expect(screen.getByText("2.3 kg")).toBeInTheDocument();
    expect(screen.getByText("2.1 kg")).toBeInTheDocument();
    // The badge glues its label, sign and unit into one string.
    expect(document.body.textContent).toContain("-0.2 kg");
  });

  /**
   * The badge printed the wire's own figure beside quantities that had
   * already been written the reader's way — "2,3 kg · 2,1 kg · -0.2 kg" —
   * the decimal mark being the only thing that disagreed inside one row.
   */
  it("writes the difference the same way as the quantities it belongs to", async () => {
    await withLanguage("pl", async () => {
      renderPage();
      await waitFor(() => {
        expect(screen.getByText("Bananas")).toBeInTheDocument();
      });

      expect(document.body.textContent).toContain("-0,2 kg");
      expect(document.body.textContent).not.toContain("-0.2 kg");
    });
  });

  it("exports a CSV that names the unit, the day, the storage and the person", async () => {
    const user = userEvent.setup();
    // jsdom's Blob cannot be read back, so the CSV is caught where it is
    // built: the parts handed to the Blob constructor are the file.
    let captured = "";
    class BlobSpy extends Blob {
      constructor(parts: BlobPart[], options?: BlobPropertyBag) {
        super(parts, options);
        captured += (parts ?? []).map(String).join("");
      }
    }
    const createObjectURL = vi.fn(() => "blob:report");
    vi.stubGlobal("Blob", BlobSpy);
    vi.stubGlobal(
      "URL",
      Object.assign(URL, {
        createObjectURL,
        revokeObjectURL: vi.fn(),
      }),
    );

    try {
      renderPage();
      await waitFor(() => {
        expect(screen.getByText("Bananas")).toBeInTheDocument();
      });
      await user.click(screen.getByRole("button", { name: "Export CSV" }));

      expect(createObjectURL).toHaveBeenCalled();
      const headerLine = captured.split("\n")[0];
      for (const column of [
        "Name",
        "Expected",
        "Counted",
        "Unit",
        "Location",
        "Started at",
        "Completed at",
        "Started by",
      ]) {
        expect(headerLine).toContain(column);
      }
      const bananaRow = captured
        .split("\n")
        .find((line) => line.includes("Bananas"));
      expect(bananaRow).toContain("kg");
      expect(bananaRow).toContain("Kitchen");
      expect(bananaRow).toContain("QA Many User");
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
