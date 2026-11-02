import React from "react";
import {
  render,
  screen,
  waitFor,
  fireEvent,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { ModulesProvider } from "@/contexts/ModulesContext";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import EquipmentLocationsPage from "../pages/EquipmentLocationsPage";
import { onePage } from "@/test/mocks/page";

// These pages hide their write actions from an account that cannot write,
// so a spec about the actions has to say who is looking at them.
beforeEach(() => {
  signInWith([
    "equipment:read",
    "equipment:write",
    "items:read",
    "locations:read",
    "locations:write",
    "categories:read",
    "categories:write",
  ]);
});

afterEach(() => {
  signOut();
});

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

/** Renders the module header the way the shell does, so its actions exist. */
function HeaderHost({ children }: { children: React.ReactNode }) {
  const [data, setData] = React.useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
      <div>{data.actions}</div>
      {children}
    </PageHeaderContext.Provider>
  );
}

const site = {
  id: "site-1",
  name: "Warsaw office",
  parent_id: null,
  description: null,
  context_tag: null,
  full_path: "Warsaw office",
  items_count: 0,
  subtree_items_count: 4,
};

const room = {
  id: "loc-1",
  name: "Server room",
  parent_id: "site-1",
  description: null,
  context_tag: "equipment",
  full_path: "Warsaw office / Server room",
  items_count: 4,
  subtree_items_count: 4,
};

const empty = {
  id: "loc-2",
  name: "Spare shelf",
  parent_id: "site-1",
  description: null,
  context_tag: "equipment",
  full_path: "Warsaw office / Spare shelf",
  items_count: 0,
  subtree_items_count: 0,
};

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter>
          <HeaderHost>{children}</HeaderHost>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
};

/**
 * Core keeps locations as Site → Zone → Location, and this screen offered a
 * name and a description — so an organization with two buildings encoded that
 * in the name. Deleting was a first-level action with no hint that location
 * is a required field of every asset standing there.
 */
describe("equipment locations and the hierarchy they live in", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/locations", () =>
        HttpResponse.json(onePage([site, room, empty])),
      ),
    );
  });

  it("leaves the add action to the header on an empty list, with the empty state's own entry as an outline", async () => {
    server.use(
      http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
    );
    render(<EquipmentLocationsPage />, { wrapper: createWrapper() });

    // The same label stands twice — header and empty state — and the view has
    // one first move: exactly one of the two is the filled button.
    await screen.findByText("No locations yet");
    const buttons = screen.getAllByRole("button", {
      name: "Add Location",
    });
    expect(buttons).toHaveLength(2);
    expect(
      buttons.filter((b) => b.className.includes("text-white")),
    ).toHaveLength(1);
  });

  it("shows where a location sits", async () => {
    render(<EquipmentLocationsPage />, { wrapper: createWrapper() });

    expect(
      await screen.findByText("Warsaw office / Server room"),
    ).toBeInTheDocument();
  });

  it("offers any location as the parent, not only the top level", async () => {
    const user = userEvent.setup();
    render(<EquipmentLocationsPage />, { wrapper: createWrapper() });
    await screen.findByText("Server room");

    fireEvent.click(screen.getByRole("button", { name: /Add location/i }));
    await user.click(
      await screen.findByRole("combobox", { name: "Parent location" }),
    );

    // ADR-018: a room inside an office holds a shelf like anything else. The
    // list used to be filtered down to locations with no parent.
    const panel = await screen.findByRole("dialog");
    expect(within(panel).getByText("Server room")).toBeInTheDocument();
    expect(within(panel).getByText("Warsaw office")).toBeInTheDocument();
  });

  it("refuses to delete a location that holds records, before the click", async () => {
    // It used to ask, then report a bare "Failed to delete" — the API has
    // always refused this, so the question had one possible answer and was
    // phrased as a mishap.
    render(<EquipmentLocationsPage />, { wrapper: createWrapper() });
    await screen.findByText("Server room");

    // Two rows hold four records: the location itself, and the site counting
    // its subtree. Both refuse.
    const refused = await screen.findAllByRole("button", {
      name: /Cannot delete: 4 records/,
    });

    expect(refused).toHaveLength(2);
    for (const button of refused) expect(button).toBeDisabled();
  });

  it("still deletes an empty one", async () => {
    render(<EquipmentLocationsPage />, { wrapper: createWrapper() });
    await screen.findByText("Spare shelf");

    const enabled = screen
      .getAllByRole("button", { name: /^Delete / })
      .filter((button) => !button.hasAttribute("disabled"));

    // Two of the three rows hold something (the site counts its subtree), so
    // exactly one Delete is live — asserting the count as well, since a change
    // that disabled every one of them would otherwise read as a pass.
    expect(enabled).toHaveLength(1);

    fireEvent.click(enabled[0]);
    await waitFor(() =>
      expect(
        screen.getByText(/Delete location "Spare shelf"/),
      ).toBeInTheDocument(),
    );
  });
});
