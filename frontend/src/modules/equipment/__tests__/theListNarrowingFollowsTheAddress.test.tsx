/** The address is the narrowing; state that only reads it at mount is a copy
 *  that goes stale the moment the module navigates within itself.
 *
 *  /equipment/locations links here with ?location=<id>. Clicking "Assets" in
 *  the module bar navigates to the bare /equipment/assets on the same route —
 *  no remount — and the mount-time copy kept the chip, the rows and the
 *  dropdown on the old narrowing while the address said "no filter". The same
 *  copy sat behind status, checked-out and category, so the tests drive all
 *  of them through the same door: a Clear naming several params must land as
 *  one address, and the Archive tab, which narrows by none of them, must not
 *  keep in the address what it silently ignores.
 */

import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Link,
  MemoryRouter,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { ModulesProvider } from "@/contexts/ModulesContext";

import AssetListPage from "../pages/AssetListPage";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({ setHeader: vi.fn() }),
}));

const STORAGES = [
  {
    id: "loc-1",
    name: "Server Room",
    context_tag: "equipment",
    behavior_mode: "NONE",
  },
];

const assetPage = {
  items: [
    {
      id: "item-1",
      name: "Asset 1",
      brand: "Dell",
      barcode: "barcode-1",
      status: "ACTIVE",
      category_id: "cat-1",
      location_id: "loc-1",
      context_tag: "equipment",
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:00:00Z",
      metadata: { equipment: { status: "AVAILABLE" } },
    },
  ],
  total: 1,
  offset: 0,
  limit: 50,
  has_more: false,
};

const emptyPage = {
  items: [],
  total: 0,
  offset: 0,
  limit: 50,
  has_more: false,
};

/** The module's own navigation (a link to the bare list) and the address it
 *  lands on, rendered beside the page so a test can read what a copy would
 *  carry. */
function Harness() {
  const location = useLocation();
  return (
    <>
      <Link to="/equipment/assets">Assets</Link>
      <span data-testid="address">{`${location.pathname}${location.search}`}</span>
      <Routes>
        <Route path="/equipment/assets" element={<AssetListPage />} />
      </Routes>
    </>
  );
}

function createWrapper(initialEntries: string[] = ["/equipment/assets"]) {
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
}

describe("the asset list narrowing follows the address", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/locations", () => HttpResponse.json(onePage(STORAGES))),
      http.get("/api/v1/categories", () => HttpResponse.json(onePage([]))),
      http.get("/api/v1/items/archived", () =>
        HttpResponse.json({ items: [], total: 0, offset: 0, limit: 50 }),
      ),
    );
  });

  it("drops the location narrowing when the module nav clears the address", async () => {
    const user = userEvent.setup();
    const requested: string[] = [];
    server.use(
      http.get("/api/v1/equipment/assets", ({ request }) => {
        requested.push(new URL(request.url).search);
        return HttpResponse.json(assetPage);
      }),
    );

    render(<Harness />, {
      wrapper: createWrapper(["/equipment/assets?location=loc-1"]),
    });

    // Arrived from a location card: the narrowing is named and asked for.
    expect(
      await screen.findByText(/Filtered by location: Server Room/),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(requested.at(-1)).toContain("location_id=loc-1"),
    );

    // The module nav goes to the bare list — a new address, not a remount.
    await user.click(screen.getByRole("link", { name: "Assets" }));

    expect(screen.getByTestId("address")).toHaveTextContent(
      /^\/equipment\/assets$/,
    );
    await waitFor(() =>
      expect(
        screen.queryByText(/Filtered by location/),
      ).not.toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(requested.at(-1)).not.toContain("location_id=loc-1"),
    );
  });

  it.each([
    ["status=AVAILABLE", "Clear status filter"],
    ["checked_out=1", "Clear checked-out filter"],
  ])(
    "drops the %s narrowing when the module nav clears the address",
    async (param, badgeLabel) => {
      const user = userEvent.setup();
      const requested: string[] = [];
      server.use(
        http.get("/api/v1/equipment/assets", ({ request }) => {
          requested.push(new URL(request.url).search);
          return HttpResponse.json(assetPage);
        }),
      );

      render(<Harness />, {
        wrapper: createWrapper([`/equipment/assets?${param}`]),
      });

      expect(
        await screen.findByRole("button", { name: badgeLabel }),
      ).toBeInTheDocument();

      await user.click(screen.getByRole("link", { name: "Assets" }));

      expect(screen.getByTestId("address")).toHaveTextContent(
        /^\/equipment\/assets$/,
      );
      await waitFor(() =>
        expect(
          screen.queryByRole("button", { name: badgeLabel }),
        ).not.toBeInTheDocument(),
      );
    },
  );

  it("clears every filter in the address with one click, not one param per navigation", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/v1/equipment/assets", () => HttpResponse.json(emptyPage)),
    );

    render(<Harness />, {
      wrapper: createWrapper([
        "/equipment/assets?location=loc-1&category=cat-1",
      ]),
    });

    expect(
      await screen.findByText(/Filtered by location: Server Room/),
    ).toBeInTheDocument();

    // Both params were named; the Clear lives in the empty state the filter
    // left behind (the panel's own Clear is a second button on screen).
    const emptyState = screen
      .getByText("No assets match the active filters")
      .closest("div") as HTMLElement;
    await user.click(within(emptyState).getByRole("button", { name: "Clear" }));

    await waitFor(() =>
      expect(screen.getByTestId("address")).toHaveTextContent(
        /^\/equipment\/assets$/,
      ),
    );
    expect(screen.queryByText(/Filtered by location/)).not.toBeInTheDocument();
  });

  it("keeps no narrowing the Archive tab silently ignores", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/v1/equipment/assets", () => HttpResponse.json(assetPage)),
    );

    render(<Harness />, {
      wrapper: createWrapper(["/equipment/assets?location=loc-1"]),
    });

    expect(
      await screen.findByText(/Filtered by location: Server Room/),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Archived" }));

    await waitFor(() =>
      expect(screen.getByTestId("address")).toHaveTextContent(
        /^\/equipment\/assets\?tab=archived$/,
      ),
    );
  });

  it("cleans a typed archive address that names a filter the tab does not have", async () => {
    server.use(
      http.get("/api/v1/equipment/assets", () => HttpResponse.json(assetPage)),
    );

    render(<Harness />, {
      wrapper: createWrapper(["/equipment/assets?tab=archived&location=loc-1"]),
    });

    await waitFor(() =>
      expect(screen.getByTestId("address")).toHaveTextContent(
        /^\/equipment\/assets\?tab=archived$/,
      ),
    );
  });
});
