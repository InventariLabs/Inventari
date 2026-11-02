import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { withModules } from "@/test/moduleList";
import { ModulesProvider } from "@/contexts/ModulesContext";
import AssetListPage from "../pages/AssetListPage";

// These pages hide their write actions from an account that cannot write,
// so a spec about the actions has to say who is looking at them.
beforeEach(() => {
  withModules("equipment");
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
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    loading: vi.fn(),
  },
}));

vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({ setHeader: vi.fn() }),
}));

function asset(id: string, name: string, assignee: string | null) {
  return {
    id,
    name,
    brand: null,
    barcode: null,
    status: "ACTIVE",
    category_id: null,
    location_id: "loc-1",
    context_tag: "equipment",
    holder_name: assignee,
    holder_kind: assignee ? "person" : null,
    serial_number: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    metadata: {
      equipment: { equipment_status: assignee ? "DEPLOYED" : "AVAILABLE" },
    },
  };
}

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter>{children}</MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
};

function listOf(items: ReturnType<typeof asset>[]) {
  return HttpResponse.json({
    items,
    total: items.length,
    offset: 0,
    limit: 50,
    has_more: false,
  });
}

// The list renders a table and a card list side by side; only CSS hides one
// of them, and jsdom has none — so every row appears twice.
async function selectEverything() {
  fireEvent.click((await screen.findAllByLabelText("Select All"))[0]);
  fireEvent.click(
    (await screen.findAllByRole("button", { name: "Return Selected" }))[0],
  );
}

/**
 * A bulk return closes open assignments. It used to send everything ticked,
 * so the dialog promised to return assets that were sitting on a shelf and
 * the backend answered with failures nobody had asked for.
 */
describe("a bulk return covers what is actually out", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("counts only the assets on loan", async () => {
    server.use(
      http.get("/api/v1/equipment/assets", () =>
        listOf([
          asset("a-1", "Laptop on loan", "Anna Kowalska"),
          asset("a-2", "Laptop on the shelf", null),
          asset("a-3", "Monitor on the shelf", null),
        ]),
      ),
    );
    render(<AssetListPage />, { wrapper: createWrapper() });
    await screen.findAllByText("Laptop on loan");

    await selectEverything();

    expect(
      (await screen.findAllByText("Return 1 selected asset?")).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getByText(
        "2 of the 3 selected assets are on a shelf; the return covers the rest.",
      ),
    ).toBeInTheDocument();
  });

  it("sends only those ids to the API", async () => {
    let sent: unknown = null;
    server.use(
      http.get("/api/v1/equipment/assets", () =>
        listOf([
          asset("a-1", "Laptop on loan", "Anna Kowalska"),
          asset("a-2", "Laptop on the shelf", null),
        ]),
      ),
      http.post("/api/v1/equipment/items/bulk-return", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({ checked_in: 1, errors: [] });
      }),
    );
    render(<AssetListPage />, { wrapper: createWrapper() });
    await screen.findAllByText("Laptop on loan");

    await selectEverything();
    fireEvent.click(
      (await screen.findAllByRole("button", { name: "Return" }))[0],
    );

    await waitFor(() => expect(sent).not.toBeNull());
    expect((sent as { item_ids: string[] }).item_ids).toEqual(["a-1"]);
  });

  it("does not open a dialog when nothing is out", async () => {
    server.use(
      http.get("/api/v1/equipment/assets", () =>
        listOf([asset("a-2", "Laptop on the shelf", null)]),
      ),
    );
    render(<AssetListPage />, { wrapper: createWrapper() });
    await screen.findAllByText("Laptop on the shelf");

    await selectEverything();

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "None of the selected assets is currently out.",
      ),
    );
    expect(screen.queryByText(/selected asset/)).not.toBeInTheDocument();
  });
});
