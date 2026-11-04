import { useCallback, useState, type ReactNode } from "react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import StockTakeCountingPage from "./StockTakeCountingPage";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";

import { signInWith } from "@/test/auth";
import { onePage } from "@/test/mocks/page";

// The page asks whether this account may write before it renders the
// form at all; rendering it signed out tests the denial instead.
beforeEach(() => {
  signInWith(["stock_takes:write"]);
});

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

// Create a stable mock for setHeader
const mockSetHeader = vi.fn();

describe("StockTakeCountingPage", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
          gcTime: 0,
        },
      },
    });
    mockSetHeader.mockClear();
    server.use(
      http.get("/api/v1/stock-takes/1", () =>
        HttpResponse.json({
          id: "1",
          name: "Stock Take 1",
          location_id: "1",
          location_name: "Fridge",
          status: "in_progress",
          items_count: 2,
          items: [
            {
              id: "sti-1",
              item_id: "1",
              name: "Milk",
              system_quantity: 2,
              counted_quantity: 2,
            },
            {
              id: "sti-2",
              item_id: "2",
              name: "Bread",
              system_quantity: 1,
              counted_quantity: 1,
            },
          ],
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
      ),
      http.get("/api/v1/locations/1/items", () =>
        HttpResponse.json(
          onePage([
            { id: "1", name: "Milk", quantity: 2 },
            { id: "2", name: "Bread", quantity: 1 },
          ]),
        ),
      ),
      http.post("/api/v1/stock-takes/1/items", () =>
        HttpResponse.json({}, { status: 201 }),
      ),
      http.post("/api/v1/stock-takes/1/complete", () => HttpResponse.json({})),
      http.post("/api/v1/stock-takes/1/cancel", () => HttpResponse.json({})),
    );
  });

  it("should display stock take items after loading", async () => {
    render(
      <MemoryRouter initialEntries={["/stock-takes/1"]}>
        <Routes>
          <Route
            path="/stock-takes/:id"
            element={
              <QueryClientProvider client={queryClient}>
                <PageHeaderContext.Provider
                  value={{ data: {}, setHeader: mockSetHeader }}
                >
                  <StockTakeCountingPage />
                </PageHeaderContext.Provider>
              </QueryClientProvider>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("Milk")).toBeInTheDocument();
      expect(screen.getByText("Bread")).toBeInTheDocument();
    });
  });

  it("should allow updating counted quantity", async () => {
    render(
      <MemoryRouter initialEntries={["/stock-takes/1"]}>
        <Routes>
          <Route
            path="/stock-takes/:id"
            element={
              <QueryClientProvider client={queryClient}>
                <PageHeaderContext.Provider
                  value={{ data: {}, setHeader: mockSetHeader }}
                >
                  <StockTakeCountingPage />
                </PageHeaderContext.Provider>
              </QueryClientProvider>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("Milk")).toBeInTheDocument();
    });

    const milkInput = screen.getByRole("textbox", {
      name: "Counted quantity of Milk",
    });

    await userEvent.clear(milkInput);
    await userEvent.type(milkInput, "3");

    expect(milkInput).toHaveValue("3");
  });

  it("should show complete button", async () => {
    render(
      <MemoryRouter initialEntries={["/stock-takes/1"]}>
        <Routes>
          <Route
            path="/stock-takes/:id"
            element={
              <QueryClientProvider client={queryClient}>
                <PageHeaderContext.Provider
                  value={{ data: {}, setHeader: mockSetHeader }}
                >
                  <StockTakeCountingPage />
                </PageHeaderContext.Provider>
              </QueryClientProvider>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      const calls = mockSetHeader.mock.calls;
      const callWithActions = calls.find(
        (call) => call[0]?.title === "Stock Take 1" && call[0]?.actions != null,
      );
      expect(callWithActions).toBeDefined();
    });
  });

  // A search hit that is NOT on the stock take list must be
  // registered as a surplus — the search is the only path to add an
  // existing product (the old behaviour silently did nothing).
  it("registers a non-listed search result as a surplus", async () => {
    server.use(
      http.get("/api/v1/stock-takes/1", () =>
        HttpResponse.json({
          id: "1",
          name: "Stock Take 1",
          location_id: "1",
          location_name: "Fridge",
          status: "in_progress",
          items_count: 1,
          items: [
            {
              id: "sti-1",
              item_id: "1",
              name: "Milk",
              system_quantity: 2,
              counted_quantity: null,
            },
          ],
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
      ),
      http.get("/api/v1/items", ({ request }) => {
        const url = new URL(request.url);
        const match = url.searchParams.get("search") === "bre";
        return HttpResponse.json({
          items: match ? [{ id: "2", name: "Bread", quantity: 1 }] : [],
          total: match ? 1 : 0,
        });
      }),
      http.get("/api/v1/locations/1/items", () =>
        HttpResponse.json(onePage([{ id: "1", name: "Milk", quantity: 2 }])),
      ),
    );
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/stock-takes/1"]}>
        <Routes>
          <Route
            path="/stock-takes/:id"
            element={
              <QueryClientProvider client={queryClient}>
                <PageHeaderContext.Provider
                  value={{ data: {}, setHeader: mockSetHeader }}
                >
                  <StockTakeCountingPage />
                </PageHeaderContext.Provider>
              </QueryClientProvider>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("Milk")).toBeInTheDocument();
    });

    await user.type(screen.getByTestId("stock-take-counting-input"), "bre");
    const breadResult = await screen.findByText("Bread");
    await user.click(breadResult);

    await waitFor(() => {
      expect(screen.getByText("1 surplus")).toBeInTheDocument();
    });
    expect(
      screen.getAllByTestId("stock-take-item-card").length,
    ).toBeGreaterThanOrEqual(2);
  });

  // in blind mode the expected quantities disappear from the cards
  // — the screen must say why instead of hiding them silently.
  it("shows a notice when blind mode is active", async () => {
    server.use(
      http.get("/api/v1/stock-takes/1", () =>
        HttpResponse.json({
          id: "1",
          name: "Stock Take 1",
          location_id: "1",
          location_name: "Fridge",
          status: "in_progress",
          blind_mode: true,
          items_count: 2,
          items: [],
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
      ),
    );

    render(
      <MemoryRouter initialEntries={["/stock-takes/1"]}>
        <Routes>
          <Route
            path="/stock-takes/:id"
            element={
              <QueryClientProvider client={queryClient}>
                <PageHeaderContext.Provider
                  value={{ data: {}, setHeader: mockSetHeader }}
                >
                  <StockTakeCountingPage />
                </PageHeaderContext.Provider>
              </QueryClientProvider>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(
        screen.getByText("Blind mode active — expected quantities are hidden."),
      ).toBeInTheDocument();
    });
  });

  it("names the counter buttons after the product they count", async () => {
    // Sixty-four buttons on a page of thirty-two products, every one of them
    // announcing itself as nothing at all.
    render(
      <MemoryRouter initialEntries={["/stock-takes/1"]}>
        <Routes>
          <Route
            path="/stock-takes/:id"
            element={
              <QueryClientProvider client={queryClient}>
                <PageHeaderContext.Provider
                  value={{ data: {}, setHeader: mockSetHeader }}
                >
                  <StockTakeCountingPage />
                </PageHeaderContext.Provider>
              </QueryClientProvider>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(
      await screen.findByRole("button", { name: "One more Milk" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "One fewer Bread" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("textbox", { name: "Counted quantity of Milk" }),
    ).toBeInTheDocument();
  });

  it("does not tell a counter their stock take is gone when the request failed", async () => {
    // Somebody halfway down a bay reads "Stock take not found" as work lost,
    // and there is no way to tell from the screen that it is only an outage.
    server.use(
      http.get(
        "/api/v1/stock-takes/1",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    render(
      <MemoryRouter initialEntries={["/stock-takes/1"]}>
        <Routes>
          <Route
            path="/stock-takes/:id"
            element={
              <QueryClientProvider client={queryClient}>
                <PageHeaderContext.Provider
                  value={{ data: {}, setHeader: mockSetHeader }}
                >
                  <StockTakeCountingPage />
                </PageHeaderContext.Provider>
              </QueryClientProvider>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("An error occurred")).toBeInTheDocument();
    expect(screen.queryByText("Stock take not found")).not.toBeInTheDocument();
  });

  it("takes the count back off the card when the server refuses the save", async () => {
    // The card and the progress bar are drawn from local state, so a refused
    // save used to leave "1 / 1 items" on a shelf nobody counted — and the
    // counter moved on to the next bay believing the work was recorded.
    server.use(
      http.get("/api/v1/stock-takes/1", () =>
        HttpResponse.json({
          id: "1",
          name: "Stock Take 1",
          location_id: "1",
          location_name: "Fridge",
          status: "in_progress",
          items_count: 1,
          items: [
            {
              id: "sti-1",
              item_id: "1",
              name: "Milk",
              system_quantity: 2,
              counted_quantity: null,
            },
          ],
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
      ),
      http.patch(
        "/api/v1/stock-takes/1/items/sti-1/count",
        () => new HttpResponse(null, { status: 403 }),
      ),
    );

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/stock-takes/1"]}>
        <Routes>
          <Route
            path="/stock-takes/:id"
            element={
              <QueryClientProvider client={queryClient}>
                <PageHeaderContext.Provider
                  value={{ data: {}, setHeader: mockSetHeader }}
                >
                  <StockTakeCountingPage />
                </PageHeaderContext.Provider>
              </QueryClientProvider>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("Milk")).toBeInTheDocument());
    expect(screen.getByText("0 / 1 items")).toBeInTheDocument();

    const quantityInput = screen.getByRole("textbox", {
      name: "Counted quantity of Milk",
    });
    await user.clear(quantityInput);
    await user.type(quantityInput, "4");
    await user.click(
      screen.getByRole("button", { name: "Save the count for Milk" }),
    );

    await waitFor(() =>
      expect(screen.getByText("0 / 1 items")).toBeInTheDocument(),
    );
    expect(quantityInput).not.toHaveValue("4");
  });
  it("marks a typed count as unsaved instead of counting it", async () => {
    // Typing a number looked exactly like saving one: the row showed
    // "Counted: 20" with the difference worked out, and the bar moved. The
    // number was gone on the way back from the door, and the bar had been
    // saying the shelf was done for the whole hour in between.
    server.use(
      http.get("/api/v1/stock-takes/1", () =>
        HttpResponse.json({
          id: "1",
          name: "Stock Take 1",
          location_id: "1",
          location_name: "Fridge",
          status: "in_progress",
          items_count: 1,
          items: [
            {
              id: "sti-1",
              item_id: "1",
              name: "Milk",
              system_quantity: 2,
              counted_quantity: null,
            },
          ],
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
      ),
      http.get("/api/v1/locations/1/items", () =>
        HttpResponse.json(onePage([{ id: "1", name: "Milk", quantity: 2 }])),
      ),
    );

    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/stock-takes/1"]}>
        <Routes>
          <Route
            path="/stock-takes/:id"
            element={
              <QueryClientProvider client={queryClient}>
                <PageHeaderContext.Provider
                  value={{ data: {}, setHeader: mockSetHeader }}
                >
                  <StockTakeCountingPage />
                </PageHeaderContext.Provider>
              </QueryClientProvider>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("Milk")).toBeInTheDocument());
    expect(screen.getByText("0 / 1 items")).toBeInTheDocument();
    expect(screen.queryByText("Not saved")).not.toBeInTheDocument();

    const countedField = screen.getByRole("textbox", {
      name: "Counted quantity of Milk",
    });
    await user.clear(countedField);
    await user.type(countedField, "20");

    expect(screen.getByText("Not saved")).toBeInTheDocument();
    expect(screen.getByText("1 count typed but not saved")).toBeInTheDocument();
    // The record says nothing was counted, and says so on the row too.
    expect(screen.getByText("0 / 1 items")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(
      screen.queryByText("1 discrepancy detected"),
    ).not.toBeInTheDocument();
  });
  describe("why a row differs", () => {
    const withRows = (flagged: number) => ({
      id: "1",
      name: "Stock Take 1",
      location_id: "1",
      location_name: "Fridge",
      status: "in_progress",
      items_count: 2,
      items: [
        {
          id: "sti-1",
          item_id: "1",
          name: "Milk",
          system_quantity: 10,
          counted_quantity: 8,
          is_discrepancy: flagged,
        },
        {
          id: "sti-2",
          item_id: "2",
          name: "Bread",
          system_quantity: 1,
          counted_quantity: 1,
          is_discrepancy: 0,
        },
      ],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    const renderPage = () =>
      render(
        <MemoryRouter initialEntries={["/stock-takes/1"]}>
          <Routes>
            <Route
              path="/stock-takes/:id"
              element={
                <QueryClientProvider client={queryClient}>
                  <PageHeaderContext.Provider
                    value={{ data: {}, setHeader: mockSetHeader }}
                  >
                    <StockTakeCountingPage />
                  </PageHeaderContext.Provider>
                </QueryClientProvider>
              }
            />
          </Routes>
        </MemoryRouter>,
      );

    it("asks only on the row that differs", async () => {
      server.use(
        http.get("/api/v1/stock-takes/1", () => HttpResponse.json(withRows(1))),
      );
      renderPage();
      await waitFor(() => expect(screen.getByText("Milk")).toBeInTheDocument());

      // One flagged row, one that matches: one question, not two.
      expect(screen.getAllByTestId("discrepancy-reason-code")).toHaveLength(1);
      expect(
        screen.getByRole("option", { name: "Lost or taken" }),
      ).toBeInTheDocument();
    });

    it("says nothing where the count agrees with the records", async () => {
      server.use(
        http.get("/api/v1/stock-takes/1", () => HttpResponse.json(withRows(0))),
      );
      renderPage();
      await waitFor(() => expect(screen.getByText("Milk")).toBeInTheDocument());

      expect(
        screen.queryByTestId("discrepancy-reason-code"),
      ).not.toBeInTheDocument();
    });

    it("holds the save until Other has been explained", async () => {
      const patches: Record<string, unknown>[] = [];
      server.use(
        http.get("/api/v1/stock-takes/1", () => HttpResponse.json(withRows(1))),
        http.patch(
          "/api/v1/stock-takes/1/items/sti-1/count",
          async ({ request }) => {
            patches.push((await request.json()) as Record<string, unknown>);
            return HttpResponse.json({ id: "sti-1" });
          },
        ),
      );
      const user = userEvent.setup();
      renderPage();
      await waitFor(() => expect(screen.getByText("Milk")).toBeInTheDocument());

      await user.selectOptions(
        screen.getByTestId("discrepancy-reason-code"),
        "OTHER",
      );
      await user.click(
        screen.getByRole("button", { name: "Save the count for Milk" }),
      );

      // Refused here rather than by the server: a rejected save takes the
      // count back off the card, so the reader would lose the number too.
      expect(patches).toHaveLength(0);
      expect(
        screen.getByText("Say what happened, or pick a named reason"),
      ).toBeInTheDocument();

      await user.type(
        screen.getByTestId("discrepancy-reason-note"),
        "Two crates went to the fair",
      );
      await user.click(
        screen.getByRole("button", { name: "Save the count for Milk" }),
      );

      await waitFor(() => expect(patches).toHaveLength(1));
      expect(patches[0].discrepancy_reason_code).toBe("OTHER");
      expect(patches[0].discrepancy_reason).toBe("Two crates went to the fair");
    });
  });
  describe("finishing right after a save", () => {
    it("waits for the saved row before it lets the count be finished", async () => {
      const counted = { value: null as number | null };
      let answerReads = () => {};
      const readsHeld = new Promise<void>((resolve) => {
        answerReads = resolve;
      });
      let reads = 0;
      vi.mocked(toast.error).mockClear();
      server.use(
        http.get("/api/v1/stock-takes/1", async () => {
          reads += 1;
          // The first read draws the page; those after the save wait here.
          if (reads > 1) await readsHeld;
          return HttpResponse.json({
            id: "1",
            name: "Stock Take 1",
            location_id: "1",
            location_name: "Fridge",
            status: "in_progress",
            require_full_count: true,
            items_count: 1,
            items: [
              {
                id: "sti-1",
                item_id: "1",
                item_name: "Milk",
                name: "Milk",
                system_quantity: 2,
                counted_quantity: counted.value,
              },
            ],
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          });
        }),
        http.patch("/api/v1/stock-takes/1/items/sti-1/count", () => {
          counted.value = 2;
          return HttpResponse.json({ id: "sti-1" });
        }),
      );
      // The page's buttons reach the screen through setHeader.
      const Header = () => {
        const [actions, setActions] = useState<ReactNode>(null);
        const setHeader = useCallback(
          (header: { actions?: ReactNode }) => setActions(header.actions),
          [],
        );
        return (
          <PageHeaderContext.Provider value={{ data: {}, setHeader }}>
            <div>{actions}</div>
            <StockTakeCountingPage />
          </PageHeaderContext.Provider>
        );
      };
      render(
        <MemoryRouter initialEntries={["/stock-takes/1"]}>
          <Routes>
            <Route
              path="/stock-takes/:id"
              element={
                <QueryClientProvider client={queryClient}>
                  <Header />
                </QueryClientProvider>
              }
            />
          </Routes>
        </MemoryRouter>,
      );
      const user = userEvent.setup();
      const box = await screen.findByRole("textbox", {
        name: "Counted quantity of Milk",
      });
      await user.type(box, "2");
      const complete = screen.getByTestId("stock-take-complete-btn");
      expect(complete).toBeEnabled();

      await user.click(
        screen.getByRole("button", { name: "Save the count for Milk" }),
      );
      // Pressed in this moment, the rows on screen would still read "not
      // counted" and the count would be refused for a product just counted.
      expect(complete).toBeDisabled();

      await waitFor(() => expect(reads).toBeGreaterThan(1));
      expect(complete).toBeDisabled();
      answerReads();
      await waitFor(() => expect(complete).toBeEnabled());

      await user.click(complete);
      expect(
        await screen.findByRole("alertdialog", {
          name: "Complete stock take",
        }),
      ).toBeInTheDocument();
      expect(toast.error).not.toHaveBeenCalled();
    });
  });

  describe("counting a row again", () => {
    const row = (extra: Record<string, unknown>) => ({
      id: "1",
      name: "Stock Take 1",
      location_id: "1",
      location_name: "Fridge",
      status: "in_progress",
      items_count: 1,
      items: [
        {
          id: "sti-1",
          item_id: "1",
          name: "Milk",
          system_quantity: 10,
          counted_quantity: 4,
          is_discrepancy: 1,
          ...extra,
        },
      ],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    const renderPage = () =>
      render(
        <MemoryRouter initialEntries={["/stock-takes/1"]}>
          <Routes>
            <Route
              path="/stock-takes/:id"
              element={
                <QueryClientProvider client={queryClient}>
                  <PageHeaderContext.Provider
                    value={{ data: {}, setHeader: mockSetHeader }}
                  >
                    <StockTakeCountingPage />
                  </PageHeaderContext.Provider>
                </QueryClientProvider>
              }
            />
          </Routes>
        </MemoryRouter>,
      );

    it("sends the row back without closing the count", async () => {
      const asked: string[] = [];
      server.use(
        http.get("/api/v1/stock-takes/1", () => HttpResponse.json(row({}))),
        http.post("/api/v1/stock-takes/1/items/sti-1/recount", ({ params }) => {
          asked.push(String(params.itemId ?? "sti-1"));
          return HttpResponse.json({ id: "sti-1" });
        }),
      );
      const user = userEvent.setup();
      renderPage();
      await waitFor(() => expect(screen.getByText("Milk")).toBeInTheDocument());

      await user.click(
        screen.getByRole("button", { name: "Count Milk again" }),
      );
      await waitFor(() => expect(asked).toHaveLength(1));
    });

    it("marks a row waiting for a second look and stops offering the button", async () => {
      server.use(
        http.get("/api/v1/stock-takes/1", () =>
          HttpResponse.json(row({ recount_requested: true })),
        ),
      );
      renderPage();
      await waitFor(() => expect(screen.getByText("Milk")).toBeInTheDocument());

      expect(screen.getByText("To count again")).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Count Milk again" }),
      ).not.toBeInTheDocument();
    });

    it("shows both numbers once the row has been counted twice", async () => {
      server.use(
        http.get("/api/v1/stock-takes/1", () =>
          HttpResponse.json(
            row({
              counted_quantity: 9,
              counts: [
                {
                  sequence: 1,
                  quantity: 4,
                  counted_at: new Date().toISOString(),
                  counted_by_name: "Anna",
                },
                {
                  sequence: 2,
                  quantity: 9,
                  counted_at: new Date().toISOString(),
                  counted_by_name: "Piotr",
                },
              ],
            }),
          ),
        ),
      );
      renderPage();
      await waitFor(() => expect(screen.getByText("Milk")).toBeInTheDocument());

      // The second number does not replace the first, and each carries the
      // name of whoever gave it.
      expect(
        screen.getByText("Count 1: 4 (Anna) · Count 2: 9 (Piotr)"),
      ).toBeInTheDocument();
    });
  });
});

/**
 * The counting screen's own controls: the filter that narrows the cards, the
 * note on a card, and the short form that adds a product nobody had listed.
 */
describe("StockTakeCountingPage — filter, notes and a product that was not listed", () => {
  const stockTake = {
    id: "1",
    name: "Stock Take 1",
    location_id: "1",
    location_name: "Fridge",
    status: "in_progress",
    items_count: 2,
    items: [
      {
        id: "sti-1",
        item_id: "1",
        name: "Milk",
        system_quantity: 10,
        counted_quantity: 8,
        is_discrepancy: 1,
      },
      {
        id: "sti-2",
        item_id: "2",
        name: "Bread",
        system_quantity: 1,
        counted_quantity: 1,
        is_discrepancy: 0,
      },
    ],
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };

  let queryClient: QueryClient;
  let patches: Record<string, unknown>[];
  let created: Record<string, unknown>[];
  let surpluses: Record<string, unknown>[];

  beforeEach(() => {
    signInWith(["stock_takes:write"]);
    setHeader.mockClear();
    patches = [];
    created = [];
    surpluses = [];
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    server.use(
      http.get("/api/v1/stock-takes/1", () => HttpResponse.json(stockTake)),
      http.get("/api/v1/locations/1/items", () =>
        HttpResponse.json(
          onePage([
            { id: "1", name: "Milk", quantity: 10 },
            { id: "2", name: "Bread", quantity: 1 },
          ]),
        ),
      ),
      http.patch(
        "/api/v1/stock-takes/1/items/:lineId/count",
        async ({ request, params }) => {
          patches.push((await request.json()) as Record<string, unknown>);
          return HttpResponse.json({ id: params.lineId });
        },
      ),
      http.post("/api/v1/items", async ({ request }) => {
        created.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(
          { id: "new-item", name: "Jam" },
          { status: 201 },
        );
      }),
      http.post("/api/v1/stock-takes/1/items", async ({ request }) => {
        surpluses.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json({ id: "sti-new" }, { status: 201 });
      }),
    );
  });

  const setHeader = vi.fn();

  const renderPage = async () => {
    render(
      <MemoryRouter initialEntries={["/stock-takes/1"]}>
        <Routes>
          <Route
            path="/stock-takes/:id"
            element={
              <QueryClientProvider client={queryClient}>
                <PageHeaderContext.Provider value={{ data: {}, setHeader }}>
                  <StockTakeCountingPage />
                </PageHeaderContext.Provider>
              </QueryClientProvider>
            }
          />
          <Route
            path="/inventory/stock-takes"
            element={<p>stock take list</p>}
          />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByText("Milk");
  };

  it("narrows the cards to the differences and brings the rest back with All", async () => {
    // A filter that could be turned on and not off again would leave the
    // counter looking at two cards while the rest of the shelf waits unseen.
    const user = userEvent.setup();
    await renderPage();
    expect(screen.getByText("Bread")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^Discrepancies/ }));
    await waitFor(() => expect(screen.queryByText("Bread")).toBeNull());
    expect(screen.getByText("Milk")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^All/ }));
    expect(await screen.findByText("Bread")).toBeInTheDocument();
  });

  it("sends the note typed on a card along with the count", async () => {
    const user = userEvent.setup();
    await renderPage();

    await user.type(
      screen.getByRole("textbox", { name: "Note about Bread" }),
      "Dented box",
    );
    const counted = screen.getByRole("textbox", {
      name: "Counted quantity of Bread",
    });
    await user.clear(counted);
    await user.type(counted, "7");
    await user.click(
      screen.getByRole("button", { name: "Save the count for Bread" }),
    );

    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toMatchObject({
      counted_quantity: 7,
      notes: "Dented box",
    });
  });

  it("creates the product in the counted location, then books it as a surplus", async () => {
    const user = userEvent.setup();
    await renderPage();

    await user.click(screen.getByRole("button", { name: "Add new item" }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), "Jam");
    await user.type(
      screen.getByRole("textbox", { name: "Barcode" }),
      "5901234123457",
    );
    const quantity = screen.getByRole("spinbutton", { name: "Quantity" });
    // An emptied box snaps back to 1, so the number is replaced, not typed.
    fireEvent.change(quantity, { target: { value: "3" } });
    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Category" }),
      "1",
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Unit" }),
      "3",
    );
    await user.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => expect(created).toHaveLength(1));
    expect(created[0]).toMatchObject({
      name: "Jam",
      barcode: "5901234123457",
      // Held at zero: the count posts the surplus when it closes.
      quantity: 0,
      category_id: "1",
      uom_id: "3",
      location_id: "1",
    });
    await waitFor(() => expect(surpluses).toHaveLength(1));
    expect(surpluses[0]).toMatchObject({
      item_id: "new-item",
      counted_quantity: 3,
    });
    // The form closes once the product exists.
    await waitFor(() =>
      expect(screen.queryByRole("textbox", { name: "Barcode" })).toBeNull(),
    );
  });

  it("steps the counted number up and down from the buttons on the card", async () => {
    const user = userEvent.setup();
    await renderPage();
    const counted = screen.getByRole("textbox", {
      name: "Counted quantity of Milk",
    });
    expect(counted).toHaveValue("8");

    await user.click(screen.getByRole("button", { name: "One more Milk" }));
    expect(counted).toHaveValue("9");

    await user.click(screen.getByRole("button", { name: "One fewer Milk" }));
    await user.click(screen.getByRole("button", { name: "One fewer Milk" }));
    expect(counted).toHaveValue("7");
    // Stepping is typing, not saving: nothing has gone to the server yet.
    expect(patches).toEqual([]);
  });

  it("offers a product found in the place but missing from the count, and puts it on the list", async () => {
    // The snapshot is silent about goods that arrived after it was taken;
    // the bar is the only place that says so.
    const user = userEvent.setup();
    server.use(
      http.get("/api/v1/stock-takes/1", () =>
        HttpResponse.json({
          ...stockTake,
          items_count: 1,
          items: [stockTake.items[0]],
        }),
      ),
    );
    await renderPage();
    expect(
      await screen.findByText(
        "1 product outside the stock take is in this location",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: "Counted quantity of Bread" }),
    ).toBeNull();

    await user.click(screen.getByRole("button", { name: "Add as surplus" }));

    expect(
      await screen.findByRole("textbox", { name: "Counted quantity of Bread" }),
    ).toHaveValue("1");
  });

  it("cancels the stock take after a confirmation and returns to the list", async () => {
    const user = userEvent.setup();
    const cancelled: Record<string, unknown>[] = [];
    server.use(
      http.patch("/api/v1/stock-takes/1/status", async ({ request }) => {
        cancelled.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json({ ...stockTake, status: "cancelled" });
      }),
    );
    await renderPage();
    const header = await waitFor(() => {
      const call = setHeader.mock.calls.find(
        ([value]) => value?.actions != null,
      );
      expect(call).toBeDefined();
      return call![0] as { actions: React.ReactNode };
    });
    render(<div>{header.actions}</div>);

    await user.click(screen.getByTestId("stock-take-cancel-btn"));
    await user.click(
      await screen.findByRole("button", { name: "Cancel stock take" }),
    );

    expect(await screen.findByText("stock take list")).toBeInTheDocument();
    expect(cancelled).toEqual([{ status: "cancelled" }]);
  });

  it("keeps the stock take when the cancellation is declined", async () => {
    const user = userEvent.setup();
    const cancelled: unknown[] = [];
    server.use(
      http.patch("/api/v1/stock-takes/1/status", async ({ request }) => {
        cancelled.push(await request.json());
        return HttpResponse.json({});
      }),
    );
    await renderPage();
    const header = await waitFor(() => {
      const call = setHeader.mock.calls.find(
        ([value]) => value?.actions != null,
      );
      expect(call).toBeDefined();
      return call![0] as { actions: React.ReactNode };
    });
    render(<div>{header.actions}</div>);

    await user.click(screen.getByTestId("stock-take-cancel-btn"));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(cancelled).toEqual([]);
    expect(screen.queryByText("stock take list")).toBeNull();
  });

  it("narrows the cards to one level of the place and shows them all again", async () => {
    // Walking a tall rack one level at a time: the other levels' cards are
    // noise until the walker gets there.
    const user = userEvent.setup();
    server.use(
      http.get("/api/v1/stock-takes/1", () =>
        HttpResponse.json({
          ...stockTake,
          items: [
            { ...stockTake.items[0], shelf_location: "A-1-01" },
            { ...stockTake.items[1], shelf_location: "B-2-01" },
          ],
        }),
      ),
    );
    await renderPage();
    const level = await screen.findByRole("combobox", {
      name: "Location level",
    });

    await user.selectOptions(level, "B");
    await waitFor(() => expect(screen.queryByText("Milk")).toBeNull());
    expect(screen.getByText("Bread")).toBeInTheDocument();

    await user.selectOptions(level, "");
    expect(await screen.findByText("Milk")).toBeInTheDocument();
  });
});
