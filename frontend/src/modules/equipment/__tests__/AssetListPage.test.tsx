import userEvent from "@testing-library/user-event";
import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import AssetListPage from "../pages/AssetListPage";
import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { http, HttpResponse } from "msw";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { onePage } from "@/test/mocks/page";
import "@/modules/equipment/module";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({
    setHeader: vi.fn(),
  }),
}));

const mockItem = (i: number) => ({
  id: `item-${i}`,
  name: `Asset ${i}`,
  brand: "Dell",
  barcode: `barcode-${i}`,
  status: "ACTIVE",
  category_id: "cat-1",
  location_id: "loc-1",
  context_tag: "equipment",
  created_at: `2024-01-${String(i).padStart(2, "0")}T00:00:00Z`,
  updated_at: `2024-01-${String(i).padStart(2, "0")}T00:00:00Z`,
  metadata: {
    equipment: {
      status: "AVAILABLE",
    },
  },
});

const firstPageMock = {
  items: Array.from({ length: 50 }, (_, i) => mockItem(i + 1)),
  total: 60,
  offset: 0,
  limit: 50,
  has_more: true,
};

const createWrapper = (initialEntries: string[] = ["/"]) => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
};

describe("AssetListPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    signOut();
  });

  it("renders without crashing", async () => {
    server.use(
      http.get("/api/v1/equipment/assets", () =>
        HttpResponse.json({
          items: [mockItem(1)],
          total: 1,
          offset: 0,
          limit: 50,
          has_more: false,
        }),
      ),
    );
    render(<AssetListPage />, { wrapper: createWrapper() });
    await waitFor(
      () => {
        expect(screen.queryAllByText("Asset 1").length).toBeGreaterThan(0);
      },
      { timeout: 5000 },
    );
  });

  it("sends offset=0&limit=50 on the first page", async () => {
    let lastQuery = "";
    server.use(
      http.get("/api/v1/equipment/assets", ({ request }) => {
        lastQuery = new URL(request.url).search;
        return HttpResponse.json(firstPageMock);
      }),
    );
    render(<AssetListPage />, { wrapper: createWrapper() });
    await waitFor(
      () => expect(screen.queryAllByText("Asset 1").length).toBeGreaterThan(0),
      { timeout: 5000 },
    );
    expect(lastQuery).toContain("limit=50");
    expect(lastQuery).toContain("offset=0");
  });

  it("renders server-paginated metadata (total in header, page indicator, Next enabled)", async () => {
    let lastSkip = -1;
    server.use(
      http.get("/api/v1/equipment/assets", ({ request }) => {
        const url = new URL(request.url);
        lastSkip = Number(url.searchParams.get("skip") ?? "0");
        return HttpResponse.json(firstPageMock);
      }),
    );
    render(<AssetListPage />, { wrapper: createWrapper() });
    await waitFor(
      () => expect(screen.queryAllByText("Asset 1").length).toBeGreaterThan(0),
      { timeout: 5000 },
    );

    // Initial request uses server pagination defaults (skip=0, limit=50).
    expect(lastSkip).toBe(0);

    // The server-driven total ("60 assets") is rendered, not items.length.
    // The pagination "page 1 / 2" indicator is present (server has 60/50=2 pages).
    await waitFor(() => {
      expect(screen.getByText(/60 assets/)).toBeInTheDocument();
      expect(screen.getByText(/1 \/ 2/)).toBeInTheDocument();
    });

    // Both pagination buttons exist; Prev is disabled on page 1, Next is enabled.
    const prevButton = screen.getByRole("button", { name: /previous/i });
    const nextButton = screen.getByRole("button", { name: /next/i });
    expect(prevButton).toBeDisabled();
    expect(nextButton).not.toBeDisabled();
  });

  it("forwards the status filter and checked_out param to the module endpoint", async () => {
    const requested: string[] = [];
    server.use(
      http.get("/api/v1/equipment/assets", ({ request }) => {
        requested.push(new URL(request.url).search);
        return HttpResponse.json(firstPageMock);
      }),
    );
    render(<AssetListPage />, {
      wrapper: createWrapper(["/equipment/assets?checked_out=1"]),
    });
    await waitFor(
      () => expect(screen.queryAllByText("Asset 1").length).toBeGreaterThan(0),
      { timeout: 5000 },
    );
    await waitFor(() => {
      expect(requested.some((q) => q.includes("checked_out=true"))).toBe(true);
    });
  });

  it("asks the server to leave out idle retired assets, and offers to show them again", async () => {
    const user = userEvent.setup();
    const requested: string[] = [];
    server.use(
      http.get("/api/v1/equipment/assets", ({ request }) => {
        requested.push(new URL(request.url).search);
        return HttpResponse.json(firstPageMock);
      }),
    );
    render(<AssetListPage />, {
      wrapper: createWrapper(["/equipment/assets?hide_retired=1"]),
    });
    await waitFor(() =>
      expect(requested.some((q) => q.includes("hide_retired=true"))).toBe(true),
    );

    await user.click(
      await screen.findByRole("button", { name: "Show retired assets" }),
    );
    await waitFor(() => expect(requested.at(-1)).not.toContain("hide_retired"));
    expect(screen.queryByText("Retired hidden")).not.toBeInTheDocument();
  });

  it("empty state leads to add-asset and import", async () => {
    signInWith(["equipment:write"]);
    server.use(
      http.get("/api/v1/equipment/assets", () =>
        HttpResponse.json({
          items: [],
          total: 0,
          offset: 0,
          limit: 50,
          has_more: false,
        }),
      ),
    );
    render(<AssetListPage />, { wrapper: createWrapper() });
    await waitFor(
      () => expect(screen.getByTestId("empty-state")).toBeInTheDocument(),
      { timeout: 5000 },
    );

    // Step 1 must carry a CTA that navigates to the add-asset form —
    // before the fix only step 3 had one, so the empty screen pushed
    // the user straight to settings.
    const firstCta = screen.getByTestId("getting-started-cta");
    expect(firstCta).toHaveTextContent("Add your first asset");
    expect(firstCta).toHaveAttribute("href", "/equipment/add");

    // A dedicated import step opens the CSV/XLSX import modal.
    fireEvent.click(screen.getByText("Import from file"));
    await waitFor(() => {
      expect(
        screen.getByText("Import Equipment from CSV / XLSX"),
      ).toBeInTheDocument();
    });
  });

  it("leaves settings to the module bar instead of repeating it in the start tile", async () => {
    server.use(
      http.get("/api/v1/equipment/assets", () =>
        HttpResponse.json({
          items: [],
          total: 0,
          offset: 0,
          limit: 50,
          has_more: false,
        }),
      ),
    );
    render(<AssetListPage />, { wrapper: createWrapper() });
    await waitFor(
      () => expect(screen.getByTestId("empty-state")).toBeInTheDocument(),
      { timeout: 5000 },
    );

    const navSettings = moduleRegistry
      .getModuleNav("equipment")
      ?.items.find((item) => item.path.endsWith("/settings"));
    expect(navSettings?.path).toBeTruthy();
    expect(
      screen.queryByRole("link", { name: "Open equipment settings" }),
    ).not.toBeInTheDocument();
  });
});

describe("AssetListPage — the archive's search", () => {
  it("tells a phrase that matched nothing apart from an empty archive", async () => {
    let archivedQuery = "";
    server.use(
      http.get("/api/v1/equipment/assets", () =>
        HttpResponse.json({
          items: [],
          total: 0,
          offset: 0,
          limit: 50,
          has_more: false,
        }),
      ),
      http.get("/api/v1/items/archived", ({ request }) => {
        archivedQuery = new URL(request.url).search;
        return HttpResponse.json({ items: [], total: 0, offset: 0, limit: 50 });
      }),
    );

    render(<AssetListPage />, {
      wrapper: createWrapper(["/equipment/assets?tab=archived"]),
    });

    await waitFor(() =>
      expect(screen.getByText("No archived assets")).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByTestId("list-search-input"), {
      target: { value: "Laptop" },
    });

    await waitFor(() => expect(archivedQuery).toContain("search=Laptop"));
    await waitFor(() => {
      expect(
        screen.getByText("No assets match your search"),
      ).toBeInTheDocument();
      expect(screen.queryByText("No archived assets")).not.toBeInTheDocument();
    });
  });
});

describe("AssetListPage — narrowed by the location you came from", () => {
  it("names the narrowing, scopes the request, and hands back the way out", async () => {
    let assetsQuery = "";
    server.use(
      http.get("/api/v1/equipment/assets", ({ request }) => {
        assetsQuery = new URL(request.url).search;
        return HttpResponse.json({
          items: [],
          total: 0,
          offset: 0,
          limit: 50,
          has_more: false,
        });
      }),
      http.get("/api/v1/locations", () =>
        HttpResponse.json(
          onePage([
            {
              id: "loc-1",
              name: "Server Room",
              context_tag: "equipment",
              behavior_mode: "NONE",
            },
          ]),
        ),
      ),
      http.get("/api/v1/categories", () => HttpResponse.json(onePage([]))),
    );

    render(<AssetListPage />, {
      wrapper: createWrapper(["/equipment/assets?location=loc-1"]),
    });

    // The narrowing is named — the location's own name, not an id — and
    // the request is scoped to it.
    await waitFor(() => {
      expect(
        screen.getByText(/Filtered by location: Server Room/),
      ).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(assetsQuery).toContain("loc-1");
    });

    // And the way out is one click: the chip clears, the URL follows.
    fireEvent.click(screen.getByLabelText("Stop filtering by this location"));
    await waitFor(() => {
      expect(
        screen.queryByText(/Filtered by location/),
      ).not.toBeInTheDocument();
    });
    expect(assetsQuery).not.toContain("loc-1");
  });
});
