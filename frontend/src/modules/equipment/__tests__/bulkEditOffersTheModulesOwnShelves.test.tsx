/**
 * The bulk edit dialogs against an organization whose tree holds food and
 * equipment locations at once.
 *
 * The "Move to location" picker was fed `useStorages()` — every location the
 * organization has — so a batch move offered the walk-in cooler next to the
 * server racks, and the flat names hid which was which: the two shelves called
 * "Shelf A" arrived as one option repeated. The same three dialogs also said
 * nothing about how many assets they were about to change, one selection
 * reading exactly like three, while the three confirmation dialogs on the very
 * same bar named their count.
 */
import React from "react";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";

import AssetListPage from "../pages/AssetListPage";
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

/** A module-owned place, as `module_scope=equipment` returns it. */
const EQUIPMENT = {
  id: "eq-rack-a",
  name: "Server Rack A",
  context_tag: "equipment",
  parent_id: "eq-room",
  full_path: "Office Building → Server Room → Server Rack A",
  usage: "internal",
};

/** An untagged place equipment already stands in — the union's second half. */
const UNTAGGED = {
  id: "plain-warehouse",
  name: "Main Warehouse",
  context_tag: null,
  parent_id: null,
  full_path: "Main Warehouse",
  usage: "internal",
};

/** The organization's kitchen. Nowhere an asset may be filed. */
const FOOD = {
  id: "food-freezer",
  name: "Chest Freezer",
  context_tag: "food",
  parent_id: "food-zone",
  full_path: "Freezer Zone → Chest Freezer",
  usage: "internal",
};

function storagesHandler() {
  return http.get("/api/v1/locations", ({ request }) => {
    const params = new URL(request.url).searchParams;
    // The module's own shelves, the union the API resolves for a module
    // screen. Everything else (a naming list, or the bare call this test
    // exists to catch) is answered with the whole organization.
    return HttpResponse.json(
      onePage(
        params.get("module_scope") === "equipment"
          ? [EQUIPMENT, UNTAGGED]
          : [FOOD, EQUIPMENT, UNTAGGED],
      ),
    );
  });
}

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

beforeEach(() => {
  server.resetHandlers();
  server.use(
    http.get("/api/v1/equipment/assets", () =>
      HttpResponse.json({
        items: [asset(1), asset(2), asset(3)],
        total: 3,
        offset: 0,
        limit: 50,
        has_more: false,
      }),
    ),
    storagesHandler(),
    http.get("/api/v1/categories", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/equipment/models", () => HttpResponse.json([])),
    http.get("/api/v1/organizations/my/members", () =>
      HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 }),
    ),
    http.get("/api/v1/partners", () =>
      HttpResponse.json({ items: [], total: 0 }),
    ),
    http.get("/api/v1/items/archived", () =>
      HttpResponse.json({ items: [], total: 0, offset: 0, limit: 50 }),
    ),
  );
  signInWith(ACCOUNT);
});

afterEach(() => {
  signOut();
});

/** Tick every row: one page, so the toolbar's toggle selects all of them. */
async function selectAll() {
  fireEvent.click(await screen.findByRole("button", { name: /select all/i }));
}

/** Open the bulk action whose bar button carries the given label. */
async function openBulkDialog(label: RegExp) {
  fireEvent.click(await screen.findByRole("button", { name: label }));
  return screen.findByRole("dialog");
}

describe("Bulk edit — the location picker offers the module's own shelves", () => {
  it("does not offer the organization's kitchen", async () => {
    const user = userEvent.setup();
    renderList();
    await selectAll();
    const dialog = await openBulkDialog(/^location$/i);

    await user.click(within(dialog).getByRole("combobox"));

    expect(await screen.findByText("Server Rack A")).toBeInTheDocument();
    // The whole point: a food location is not a place equipment may be sent.
    expect(screen.queryByText("Chest Freezer")).not.toBeInTheDocument();
  });

  it("names a place by its full path, so two shelves are not one option", async () => {
    const user = userEvent.setup();
    renderList();
    await selectAll();
    const dialog = await openBulkDialog(/^location$/i);

    await user.click(within(dialog).getByRole("combobox"));

    // The name, with the way to it under it.
    expect(await screen.findByText("Server Rack A")).toBeInTheDocument();
    expect(
      screen.getByText("Office Building › Server Room"),
    ).toBeInTheDocument();
  });
});

describe("Bulk edit — every dialog says what it reaches", () => {
  it("names the count in all three, as the confirmations on the same bar do", async () => {
    renderList();
    await selectAll();

    let dialog = await openBulkDialog(/^location$/i);
    expect(dialog).toHaveTextContent("Move 3 assets to a location");
    fireEvent.click(within(dialog).getByRole("button", { name: /cancel/i }));

    dialog = await openBulkDialog(/^status$/i);
    expect(dialog).toHaveTextContent("Change status of 3 assets");
    fireEvent.click(within(dialog).getByRole("button", { name: /cancel/i }));

    dialog = await openBulkDialog(/^assign$/i);
    expect(dialog).toHaveTextContent("Assign 3 assets to a person");
  });

  it("inflects for a single asset", async () => {
    server.use(
      http.get("/api/v1/equipment/assets", () =>
        HttpResponse.json({
          items: [asset(1)],
          total: 1,
          offset: 0,
          limit: 50,
          has_more: false,
        }),
      ),
    );
    renderList();
    await selectAll();

    const dialog = await openBulkDialog(/^location$/i);

    await waitFor(() =>
      expect(dialog).toHaveTextContent("Move 1 asset to a location"),
    );
  });
});
