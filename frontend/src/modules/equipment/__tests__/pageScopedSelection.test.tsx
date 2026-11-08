import React from "react";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";

import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";

import AssetListPage from "../pages/AssetListPage";
import { AssetBulkActionsBar } from "../components/AssetBulkActionsBar";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    loading: vi.fn(),
  },
}));

vi.mock("@/contexts/ModulesContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ModulesContext")>()),
  useModules: () => ({
    enabledModules: ["equipment"],
    isModuleEnabled: () => true,
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

/**
 * "Select All" selected the page, and nothing said so.
 *
 * With 61 assets over two pages, the button took 50 and the bar reported "50
 * selected" beside a header reading "61 assets" -- two numbers about what the
 * reader took to be one set. Archive Selected then archived 50 and left 11,
 * with nothing on the screen to mark the eleven as untouched. The bulk return
 * modal already knew how to count a partial scope aloud; the list did not.
 */
function PageHeaderHost({ children }: { children: React.ReactNode }) {
  const [data, setData] = React.useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
      {children}
    </PageHeaderContext.Provider>
  );
}

function renderList() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/equipment/assets"]}>
        <PageHeaderHost>
          <AssetListPage />
        </PageHeaderHost>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const ACCOUNT = ["equipment:read", "equipment:write", "items:read"];

function asset(n: number) {
  return {
    id: `asset-${n}`,
    name: `Laptop ${n}`,
    quantity: 1,
    meta_data: { equipment: { status: "AVAILABLE" } },
  };
}

/** `total` is what the filter matches; `pageSize` is what one page holds. */
function listOf(pageSize: number, total: number) {
  return http.get("/api/v1/equipment/assets", () =>
    HttpResponse.json({
      items: Array.from({ length: pageSize }, (_, i) => asset(i + 1)),
      total,
      offset: 0,
      limit: 50,
      has_more: total > pageSize,
    }),
  );
}

beforeEach(() => {
  server.resetHandlers();
  server.use(
    http.get("/api/v1/categories", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/equipment/models", () => HttpResponse.json([])),
    http.get("/api/v1/items/archived", () =>
      HttpResponse.json({ items: [], total: 0, offset: 0, limit: 50 }),
    ),
  );
  signInWith(ACCOUNT);
});

afterEach(() => {
  signOut();
});

describe("Asset list — the selection says how far it reaches", () => {
  it("calls the button Select page when the filter runs past one page", async () => {
    server.use(listOf(50, 61));
    renderList();

    expect(
      await screen.findByRole("button", { name: /select page/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^select all$/i }),
    ).not.toBeInTheDocument();
  });

  it("still calls it Select all when one page holds everything", async () => {
    server.use(listOf(3, 3));
    renderList();

    expect(
      await screen.findByRole("button", { name: /select all/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /select page/i }),
    ).not.toBeInTheDocument();
  });

  it("speaks the bar's clear words once everything is selected", async () => {
    // With every row ticked, the toggle above the list and the X in the bulk
    // bar clear the very same selection — "Deselect All" beside a "Clear
    // selection" X was one action wearing two names.
    server.use(listOf(3, 3));
    renderList();

    fireEvent.click(await screen.findByRole("button", { name: /select all/i }));

    const clearButtons = await screen.findAllByRole("button", {
      name: "Clear selection",
    });
    expect(clearButtons).toHaveLength(2);
    expect(
      screen.queryByRole("button", { name: /deselect/i }),
    ).not.toBeInTheDocument();
  });

  it("names the records the selection cannot reach", async () => {
    server.use(listOf(50, 61));
    renderList();

    fireEvent.click(
      await screen.findByRole("button", { name: /select page/i }),
    );

    expect(
      await screen.findByText(/only this page is selected/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/11 more assets match/i)).toBeInTheDocument();
  });

  it("says nothing about rows that sit on the same page, ticked or not", async () => {
    // Two of the three rows are one tap away on this very page: nothing is
    // out of reach, so the bar must not claim that only a page is selected.
    server.use(listOf(3, 3));
    renderList();

    fireEvent.click(
      (await screen.findAllByLabelText(/select asset laptop 1$/i))[0],
    );

    expect(await screen.findByText(/1 selected/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/only this page is selected/i),
    ).not.toBeInTheDocument();
  });

  it("counts only the rows on other pages as out of reach", async () => {
    server.use(listOf(50, 61));
    renderList();

    fireEvent.click(
      (await screen.findAllByLabelText(/select asset laptop 1$/i))[0],
    );

    expect(
      await screen.findByText(/11 more assets match/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /select all 61/i }),
    ).toBeInTheDocument();
  });

  it("says nothing about other pages when the selection covers them all", async () => {
    server.use(listOf(3, 3));
    renderList();

    fireEvent.click(await screen.findByRole("button", { name: /select all/i }));

    expect(await screen.findByText(/3 selected/i)).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.queryByText(/only this page is selected/i),
      ).not.toBeInTheDocument(),
    );
  });
});

describe("Asset bulk bar — the out-of-reach count is its own sentence", () => {
  const noop = {
    onBulkRetire: vi.fn(),
    onBulkArchive: vi.fn(),
    onBulkPrintLabels: vi.fn(),
    onBulkReturn: vi.fn(),
    onBulkPurge: vi.fn(),
    onBulkChangeStatus: vi.fn(),
    onBulkChangeLocation: vi.fn(),
    onBulkAssignTo: vi.fn(),
    onClearSelection: vi.fn(),
    onSelectAllMatching: vi.fn(),
    allMatching: false,
  };

  // The bar's "Send to printer" asks the print queue for printers.
  const withQueries = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={new QueryClient()}>
      {children}
    </QueryClientProvider>
  );

  it("reads as one asset when exactly one is out of reach", () => {
    render(
      <AssetBulkActionsBar
        selectedCount={50}
        unreachedMatches={1}
        matchingTotal={51}
        listTab="active"
        {...noop}
      />,
      { wrapper: withQueries },
    );

    expect(screen.getByText(/1 more asset matches/i)).toBeInTheDocument();
  });

  it("keeps quiet at zero", () => {
    render(
      <AssetBulkActionsBar
        selectedCount={50}
        unreachedMatches={0}
        matchingTotal={50}
        listTab="active"
        {...noop}
      />,
      { wrapper: withQueries },
    );

    expect(
      screen.queryByText(/only this page is selected/i),
    ).not.toBeInTheDocument();
  });
});

describe("Asset list — the selection can reach past the page", () => {
  it("offers to take everything the filters match, and says how many", async () => {
    server.use(listOf(50, 61));
    renderList();

    fireEvent.click(
      await screen.findByRole("button", { name: /select page/i }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: /select all 61/i }),
    );

    expect(
      await screen.findByText(/is selected \(61 assets\)/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/only this page is selected/i),
    ).not.toBeInTheDocument();
    // The whole-set scope only knows the two actions the server can run
    // over a filter; the rest still need rows the reader can see.
    expect(
      screen.queryByRole("button", { name: /return selected/i }),
    ).not.toBeInTheDocument();
  });

  it("archives by filter and the confirmation counts the whole set", async () => {
    let body: unknown = null;
    server.use(
      listOf(50, 61),
      http.post(
        "/api/v1/equipment/assets/matching/archive",
        async ({ request }) => {
          body = await request.json();
          return HttpResponse.json({ archived: 61, errors: [] });
        },
      ),
    );
    renderList();

    fireEvent.click(
      await screen.findByRole("button", { name: /select page/i }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: /select all 61/i }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: /archive selected/i }),
    );

    const dialog = await screen.findByRole("alertdialog");
    expect(
      within(dialog).getByText(/archive 61 selected assets/i),
    ).toBeInTheDocument();
    fireEvent.click(
      within(dialog).getByRole("button", { name: /archive selected/i }),
    );

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(vi.mocked(toast.success).mock.calls[0][0]).toMatch(/61/);
    expect(body).toEqual({ checked_out: false, hide_retired: false });
  });

  it("drops back to the page when a row is unticked", async () => {
    server.use(listOf(50, 61));
    renderList();

    fireEvent.click(
      await screen.findByRole("button", { name: /select page/i }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: /select all 61/i }),
    );
    // The row renders once as a table row and once as a card; either tick
    // narrows the scope.
    fireEvent.click(
      (await screen.findAllByLabelText(/select asset laptop 1$/i))[0],
    );

    expect(await screen.findByText(/49 selected/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/everything matching your filters is selected/i),
    ).not.toBeInTheDocument();
  });
});

describe("Asset list — a bulk action reports what it covered", () => {
  it("names the count it archived", async () => {
    server.use(
      listOf(50, 61),
      http.post("/api/v1/equipment/items/bulk-archive", () =>
        HttpResponse.json({ archived: 50, errors: [] }),
      ),
    );
    renderList();

    fireEvent.click(
      await screen.findByRole("button", { name: /select page/i }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: /archive selected/i }),
    );

    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(
      within(dialog).getByRole("button", { name: /archive selected/i }),
    );

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(vi.mocked(toast.success).mock.calls[0][0]).toMatch(/50/);
  });
});
