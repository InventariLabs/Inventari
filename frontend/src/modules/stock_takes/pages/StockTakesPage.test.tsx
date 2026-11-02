import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { BrowserRouter, MemoryRouter, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import StockTakesPage from "./StockTakesPage";
import { useAuthStore } from "@/store/authStore";
import { serveLocations } from "@/test/serveLocations";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import type { ReactNode } from "react";

import * as modulesCtx from "@/contexts/ModulesContext";
import { onePage } from "@/test/mocks/page";

beforeEach(() => {
  vi.spyOn(modulesCtx, "useModules").mockReturnValue({
    enabledModules: ["stock_takes"],
    isModuleEnabled: (name: string) => name === "stock_takes",
    isLoading: false,
    refreshModules: vi.fn(),
    focusModule: null,
    hiddenModules: [],
  });
});

let queryClient: QueryClient;
const mockSetHeader = vi.fn();

const headerContextValue = {
  data: {
    title: "Stock Takes",
    subtitle: "Manage stock takes of your storages",
    actions: null,
  },
  setHeader: mockSetHeader,
};

function Wrapper({ children }: { children: ReactNode }) {
  return (
    <PageHeaderContext.Provider value={headerContextValue}>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>{children}</BrowserRouter>
      </QueryClientProvider>
    </PageHeaderContext.Provider>
  );
}

describe("StockTakesPage", () => {
  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
          refetchOnWindowFocus: false,
        },
      },
    });

    server.use(
      http.get("/api/v1/stock-takes", () =>
        HttpResponse.json({
          items: [
            {
              id: "1",
              name: "Stock Take 1",
              status: "in_progress",
              started_at: new Date().toISOString(),
              location_name: "Fridge",
              items_count: 10,
              counted_items_count: 5,
              progress_percent: 50,
              discrepancies_count: 0,
            },
            {
              id: "2",
              name: "Stock Take 2",
              status: "completed",
              started_at: new Date().toISOString(),
              location_name: "Pantry",
              items_count: 20,
              counted_items_count: 20,
              progress_percent: 100,
              discrepancies_count: 2,
            },
          ],
          total: 2,
          limit: 50,
          offset: 0,
          has_more: false,
        }),
      ),
      http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
    );

    useAuthStore.setState({
      user: {
        is_blocked: false,
        is_superuser: false,
        is_active: true,
        id: "1",
        full_name: "Test User",
        email: "test@example.com",
        preferred_language: "en",
        role: "user",
        // Starting and deleting a count are writes; without these the page under
        // test is the read-only one.
        permissions: ["stock_takes:read", "stock_takes:write"],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      isAuthenticated: true,
    });
  });

  it("should render stock takes page with filter tabs", async () => {
    render(
      <Wrapper>
        <StockTakesPage />
      </Wrapper>,
    );

    await waitFor(() => {
      expect(screen.getByText("All")).toBeInTheDocument();
    });
  });

  it("should set page header with create button", async () => {
    render(
      <Wrapper>
        <StockTakesPage />
      </Wrapper>,
    );

    await waitFor(() => {
      expect(mockSetHeader).toHaveBeenCalledWith(
        expect.objectContaining({
          actions: expect.anything(),
        }),
      );
    });
  });

  it("sends the back arrow where the page was linked from", async () => {
    window.history.pushState({ usr: { backTo: "/warehouse/todo" } }, "");
    render(
      <Wrapper>
        <StockTakesPage />
      </Wrapper>,
    );
    await waitFor(() => {
      expect(mockSetHeader).toHaveBeenCalledWith(
        expect.objectContaining({ backTo: "/warehouse/todo" }),
      );
    });
    window.history.pushState(null, "");
  });

  it("should render stock takes list", async () => {
    render(
      <Wrapper>
        <StockTakesPage />
      </Wrapper>,
    );

    await waitFor(() => {
      expect(screen.getByText(/Stock Take 1/i)).toBeInTheDocument();
      expect(screen.getByText(/Stock Take 2/i)).toBeInTheDocument();
    });
  });

  it("leads an admin to the module's settings, where counting by age is set", async () => {
    render(
      <Wrapper>
        <StockTakesPage />
      </Wrapper>,
    );
    expect(await screen.findByText("Stock Take 1")).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Module settings" }),
    ).not.toBeInTheDocument();

    const user = useAuthStore.getState().user!;
    act(() => {
      useAuthStore.setState({
        user: { ...user, permissions: [...user.permissions, "admin:access"] },
      });
    });

    expect(
      await screen.findByRole("link", { name: "Module settings" }),
    ).toHaveAttribute("href", "/settings/modules/stock_takes");
  });

  it("opens the form with the location it was linked from", async () => {
    serveLocations([
      { id: "s1", name: "Rack", parent_id: null },
      { id: "s2", name: "Yard", parent_id: null },
    ]);
    render(
      <PageHeaderContext.Provider value={headerContextValue}>
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={["/?new=s1"]}>
            <StockTakesPage />
          </MemoryRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    const place = await screen.findByRole("combobox", { name: /Location/ });
    await waitFor(() => expect(place).toHaveTextContent("Rack"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  // when the API omits progress_percent the page must compute it
  // from the counts already present in the payload, not show 0 %.
  it("computes progress from counts when API omits progress_percent", async () => {
    server.use(
      http.get("/api/v1/stock-takes", () =>
        HttpResponse.json({
          items: [
            {
              id: "3",
              name: "Legacy Stock Take",
              status: "in_progress",
              started_at: new Date().toISOString(),
              location_name: "Shelf A",
              items_count: 10,
              counted_items_count: 6,
              discrepancies_count: 0,
            },
          ],
          total: 1,
          limit: 50,
          offset: 0,
          has_more: false,
        }),
      ),
    );
    render(
      <Wrapper>
        <StockTakesPage />
      </Wrapper>,
    );

    await waitFor(() => {
      expect(screen.getByText("60%")).toBeInTheDocument();
      expect(screen.getByText(/Shelf A/i)).toBeInTheDocument();
    });
  });

  /**
   * The card lifted under the pointer and its title changed colour, and the
   * only thing that actually navigated was the button at the far end. The
   * title is the link now, stretched over the card.
   */
  it("makes the row title the link, and only one link per row", async () => {
    render(
      <Wrapper>
        <StockTakesPage />
      </Wrapper>,
    );

    const inProgress = await screen.findByRole("link", {
      name: "Stock Take 1",
    });
    expect(inProgress).toHaveAttribute(
      "href",
      "/inventory/stock-takes/1/counting",
    );

    const completed = screen.getByRole("link", { name: "Stock Take 2" });
    expect(completed).toHaveAttribute(
      "href",
      "/inventory/stock-takes/2/report",
    );

    // The status button leads to the same place and is hidden as a duplicate.
    expect(screen.getAllByRole("link")).toHaveLength(2);
  });

  it("does not report an empty board when the request failed", async () => {
    // "No stock takes" over nine counts in progress invites a tenth count of a
    // location somebody else is already walking.
    server.use(
      http.get(
        "/api/v1/stock-takes",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    render(
      <Wrapper>
        <StockTakesPage />
      </Wrapper>,
    );

    expect(await screen.findByText("An error occurred")).toBeInTheDocument();
    expect(screen.queryByText(/no stock takes/i)).not.toBeInTheDocument();
  });
});

/**
 * A reader sees the counts and none of the ways into them.
 *
 * Every mutating method on this module's router asks for `stock_takes:write`,
 * and counting is what a stock take is for — so "Start" and "Continue" go
 * with the delete. The report of a finished count is a read and stays.
 */
describe("StockTakesPage — an account that may not count", () => {
  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false, refetchOnWindowFocus: false },
      },
    });
    server.use(
      http.get("/api/v1/stock-takes", () =>
        HttpResponse.json({
          items: [
            {
              id: "1",
              name: "Stock Take 1",
              status: "in_progress",
              started_at: new Date().toISOString(),
              location_name: "Fridge",
              items_count: 10,
              counted_items_count: 5,
              progress_percent: 50,
              discrepancies_count: 0,
            },
            {
              id: "2",
              name: "Stock Take 2",
              status: "completed",
              started_at: new Date().toISOString(),
              location_name: "Pantry",
              items_count: 20,
              counted_items_count: 20,
              progress_percent: 100,
              discrepancies_count: 2,
            },
          ],
          total: 2,
          limit: 50,
          offset: 0,
          has_more: false,
        }),
      ),
      http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
    );
    useAuthStore.setState({
      user: {
        is_blocked: false,
        is_superuser: false,
        is_active: true,
        id: "1",
        full_name: "Reader",
        email: "reader@example.com",
        preferred_language: "en",
        role: "user",
        permissions: ["stock_takes:read"],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      isAuthenticated: true,
    });
  });

  it("says why, registers no header action, and offers no way to count", async () => {
    render(<StockTakesPage />, { wrapper: Wrapper });

    expect(
      await screen.findByText(/you can view this, not change it/i),
    ).toBeInTheDocument();
    expect(await screen.findByText("Stock Take 1")).toBeInTheDocument();

    const calls = mockSetHeader.mock.calls;
    expect(calls[calls.length - 1][0].actions).toBeUndefined();
    expect(
      screen.queryByRole("button", { name: /continue/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^start$/i }),
    ).not.toBeInTheDocument();
  });

  it("keeps the report of a finished count", async () => {
    render(<StockTakesPage />, { wrapper: Wrapper });

    expect(await screen.findByText("Stock Take 2")).toBeInTheDocument();
    // The card is the link and its button is decorative (`aria-hidden`), so
    // the label is what there is to assert on.
    expect(screen.getByText(/report/i)).toBeInTheDocument();
  });
});

/**
 * The page's own controls. Each is a closure only a click reaches; a handler
 * that moves the screen but not the request leaves the wrong rows on it.
 */
describe("StockTakesPage — what its controls do", () => {
  const summary = (id: string, name: string, status: string) => ({
    id,
    name,
    status,
    started_at: new Date().toISOString(),
    location_name: "Fridge",
    items_count: 10,
    counted_items_count: 5,
    progress_percent: 50,
    discrepancies_count: 0,
  });

  const serveList = (
    total: number,
    items = [summary("1", "Stock Take 1", "in_progress")],
  ) => {
    const queries: URLSearchParams[] = [];
    server.use(
      http.get("/api/v1/stock-takes", ({ request }) => {
        queries.push(new URL(request.url).searchParams);
        return HttpResponse.json({
          items,
          total,
          limit: 50,
          offset: 0,
          has_more: false,
        });
      }),
      http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
    );
    return queries;
  };

  /** Where the router stands, written out so a test can read it. */
  function Here() {
    const location = useLocation();
    return (
      <p data-testid="here">
        {location.pathname}
        {location.search}
      </p>
    );
  }

  const renderAt = (path = "/") =>
    render(
      <PageHeaderContext.Provider value={headerContextValue}>
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={[path]}>
            <StockTakesPage />
            <Here />
          </MemoryRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

  const drawHeader = () => {
    const header = mockSetHeader.mock.calls.at(-1)?.[0] as {
      actions: ReactNode;
    };
    render(<div>{header.actions}</div>);
  };

  beforeEach(() => {
    mockSetHeader.mockClear();
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false, refetchOnWindowFocus: false },
      },
    });
    useAuthStore.setState({
      user: {
        is_blocked: false,
        is_superuser: false,
        is_active: true,
        id: "1",
        full_name: "Test User",
        email: "test@example.com",
        preferred_language: "en",
        role: "user",
        permissions: ["stock_takes:read", "stock_takes:write"],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      isAuthenticated: true,
    });
  });

  it("takes the header's count button to the location counting screen", async () => {
    serveList(1);
    renderAt();
    await screen.findByText("Stock Take 1");

    drawHeader();
    fireEvent.click(screen.getByRole("button", { name: "Count a location" }));

    await waitFor(() =>
      expect(screen.getByTestId("here")).toHaveTextContent(
        "/inventory/stock-takes/count",
      ),
    );
  });

  it("opens the new-stock-take form from the header and closes it with Cancel", async () => {
    serveList(1);
    renderAt();
    await screen.findByText("Stock Take 1");

    drawHeader();
    fireEvent.click(screen.getByRole("button", { name: "New stock take" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("clears the link's preset location when the form it opened is closed", async () => {
    // Left in the address, `?new=` would reopen the form on every refresh.
    serveList(1);
    renderAt("/?new=s1");
    await screen.findByRole("dialog");
    expect(screen.getByTestId("here")).toHaveTextContent("/?new=s1");

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() =>
      expect(screen.getByTestId("here")).toHaveTextContent(/^\/$/),
    );
  });

  it("opens on the status its address names, so a count of those opens those", async () => {
    const queries = serveList(3);
    renderAt("/?status=in_progress");

    await screen.findByText("Stock Take 1");
    expect(queries.at(-1)?.get("status_filter")).toBe("in_progress");
    expect(screen.getByRole("tab", { name: "In progress" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("asks the server for one status at a time and starts again from the first page", async () => {
    const queries = serveList(120);
    renderAt();
    await screen.findByText("Stock Take 1");

    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(queries.at(-1)?.get("offset")).toBe("50"));

    await userEvent.click(screen.getByRole("tab", { name: "Completed" }));

    await waitFor(() => {
      const last = queries.at(-1);
      expect(last?.get("status_filter")).toBe("completed");
      expect(last?.get("offset")).toBe("0");
    });
  });

  it("pages back to the previous fifty", async () => {
    const queries = serveList(120);
    renderAt();
    await screen.findByText("Stock Take 1");

    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(queries.at(-1)?.get("offset")).toBe("50"));
    fireEvent.click(screen.getByRole("button", { name: "Previous page" }));

    await waitFor(() => expect(queries.at(-1)?.get("offset")).toBe("0"));
  });

  it("deletes a stock take only after the confirmation", async () => {
    serveList(1);
    const deleted: string[] = [];
    server.use(
      http.delete("/api/v1/stock-takes/:id", ({ params }) => {
        deleted.push(String(params.id));
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderAt();
    await screen.findByText("Stock Take 1");

    fireEvent.click(screen.getByRole("button", { name: "Delete stock take" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull(),
    );
    expect(deleted).toEqual([]);

    fireEvent.click(screen.getByRole("button", { name: "Delete stock take" }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));

    await waitFor(() => expect(deleted).toEqual(["1"]));
  });

  it("offers to start the first stock take from an empty board", async () => {
    serveList(0, []);
    renderAt();
    await screen.findByText("No stock takes");

    // The header carries its own copy of the button; this is the page's.
    fireEvent.click(screen.getByRole("button", { name: "New stock take" }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("names the status that came up empty, and still offers a new count", async () => {
    serveList(0, []);
    renderAt();
    await screen.findByText("No stock takes");

    await userEvent.click(screen.getByRole("tab", { name: /Cancelled/ }));

    expect(
      await screen.findByText('No stock takes with status "Cancelled"'),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "New stock take" }),
    ).toBeInTheDocument();
  });
});
