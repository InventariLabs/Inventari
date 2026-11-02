import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { moduleRegistry, slotComponent } from "@/lib/moduleRegistry";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { signInWith, signOut } from "@/test/auth";
import { makeStorageSummary } from "@/test/factories/storage";
import type { StorageLocation } from "@/types";
import { StorageProductsTab } from "./StorageProductsTab";

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
    loading: vi.fn(),
    dismiss: vi.fn(),
  },
}));

// The product editor belongs to the inventory module; a stand-in that offers
// the one thing the page depends on — a way to close it again.
const enabled = vi.hoisted(() => ({ modules: ["spaces_products_demo"] }));
vi.mock("@/contexts/ModulesContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ModulesContext")>()),
  useModules: () => ({ enabledModules: enabled.modules }),
}));

function EditorStandIn({
  data,
}: {
  data: { itemId: string; onClose: () => void };
}) {
  return (
    <div role="dialog" aria-label="Product editor">
      Editing {data.itemId}
      <button onClick={data.onClose}>Close editor</button>
    </div>
  );
}

moduleRegistry.register({
  name: "spaces_products_demo",
  routes: [],
  slots: [
    {
      slot: "storage_item_edit_modal",
      component: slotComponent(EditorStandIn),
    },
  ],
});

const shelf = {
  ...makeStorageSummary({ id: "shelf", name: "Shelf A" }),
  description: null,
  location_details: null,
} as unknown as StorageLocation;

const shelfRow = makeStorageSummary({
  id: "shelf",
  name: "Shelf A",
  direct_children_count: 0,
});

const item = (
  id: string,
  name: string,
  extra: Record<string, unknown> = {},
) => ({
  id,
  name,
  quantity: "3",
  location_id: "shelf",
  category_id: null,
  added_date: "2026-10-01",
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
  is_deleted: false,
  uom: { symbol: "kg", rounding: 0 },
  ...extra,
});

const category = (id: string, name: string) => ({
  id,
  name,
  code: null,
  icon: null,
  color: null,
  is_active: true,
});

const flour = item("i-flour", "Flour", { category_id: "c-baking" });
const milk = item("i-milk", "Milk", { category_id: "c-dairy" });
const salt = item("i-salt", "Table salt");

function renderTab(
  props: Partial<React.ComponentProps<typeof StorageProductsTab>> = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <StorageProductsTab
          storage={shelf}
          summary={shelfRow}
          isArchived={false}
          canWriteItems
          {...props}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const serveShelf = (rows: unknown[]) =>
  server.use(
    http.get("/api/v1/locations/:id/items", ({ params }) =>
      HttpResponse.json(onePage(params.id === "shelf" ? rows : [])),
    ),
    http.get("/api/v1/categories", () =>
      HttpResponse.json(
        onePage([category("c-dairy", "Dairy"), category("c-baking", "Baking")]),
      ),
    ),
  );

/** The table comes before the phone cards in the document. */
const tableRow = async (name: string) => {
  const rows = await screen.findAllByRole("row");
  const row = rows.find((candidate) => candidate.textContent?.includes(name));
  if (!row) throw new Error(`no table row for ${name}`);
  return row;
};

describe("StorageProductsTab — removing and deleting a product", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signInWith(["locations:read", "items:read", "items:write", "items:delete"]);
    serveShelf([flour, salt]);
    return () => signOut();
  });

  it("removes one unit of the product whose Remove was pressed, and says what is left", async () => {
    const bodies: Array<{ id: string; body: unknown }> = [];
    server.use(
      http.patch("/api/v1/items/:id/consume", async ({ params, request }) => {
        bodies.push({ id: String(params.id), body: await request.json() });
        return HttpResponse.json({ ...flour, quantity: "2" });
      }),
    );
    renderTab();

    await userEvent.click(
      within(await tableRow("Flour")).getByRole("button", { name: "Remove" }),
    );

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(bodies).toEqual([
      { id: "i-flour", body: expect.objectContaining({ quantity: 1 }) },
    ]);
    expect(toast.success).toHaveBeenCalledWith("Removed 1 unit — 2 kg left");
  });

  it("announces a finished product instead of a remainder when the last unit goes", async () => {
    server.use(
      http.patch("/api/v1/items/:id/consume", () =>
        HttpResponse.json({ ...salt, quantity: "0" }),
      ),
    );
    renderTab();

    await userEvent.click(
      within(await tableRow("Table salt")).getByRole("button", {
        name: "Remove",
      }),
    );

    await waitFor(() => expect(toast.success).toHaveBeenCalledTimes(1));
    expect(toast.success).toHaveBeenCalledWith("Success");
  });

  it("shows the server's reason when a unit cannot be removed", async () => {
    server.use(
      http.patch("/api/v1/items/:id/consume", () =>
        HttpResponse.json({ detail: "Not enough stock" }, { status: 400 }),
      ),
    );
    renderTab();

    await userEvent.click(
      within(await tableRow("Flour")).getByRole("button", { name: "Remove" }),
    );

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Not enough stock"),
    );
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("deletes the product only after the question is confirmed", async () => {
    const deleted: string[] = [];
    server.use(
      http.delete("/api/v1/items/:id", ({ params }) => {
        deleted.push(String(params.id));
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderTab();

    const trash = within(await tableRow("Flour")).getByRole("button", {
      name: "Delete",
    });
    await userEvent.click(trash);
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Cancel" }),
    );
    expect(deleted).toEqual([]);

    await userEvent.click(trash);
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Delete",
      }),
    );

    await waitFor(() => expect(deleted).toEqual(["i-flour"]));
  });
});

describe("StorageProductsTab — filtering by category", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signInWith(["locations:read", "items:read", "items:write"]);
    serveShelf([milk, flour, salt]);
    return () => signOut();
  });

  it("narrows the list to one category, then to uncategorised products, then back to all", async () => {
    renderTab();
    await tableRow("Flour");
    const filters = screen.getByRole("group", { name: "Filter by category" });

    await userEvent.click(
      await within(filters).findByRole("button", { name: /Baking/ }),
    );
    expect(screen.queryByText("Table salt")).not.toBeInTheDocument();
    expect(screen.queryByText("Milk")).not.toBeInTheDocument();
    expect(screen.getAllByText("Flour").length).toBeGreaterThan(0);
    // Categories are offered alphabetically, whatever order the items came in.
    expect(
      within(filters)
        .getAllByRole("button")
        .map((button) => button.textContent?.trim()),
    ).toEqual(["All", "Baking", "Dairy", "No category"]);

    await userEvent.click(
      within(filters).getByRole("button", { name: "No category" }),
    );
    expect(screen.queryByText("Flour")).not.toBeInTheDocument();
    expect(screen.queryByText("Milk")).not.toBeInTheDocument();
    expect(screen.getAllByText("Table salt").length).toBeGreaterThan(0);

    await userEvent.click(within(filters).getByRole("button", { name: "All" }));
    expect(screen.getAllByText("Milk").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Flour").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Table salt").length).toBeGreaterThan(0);
  });
});

describe("StorageProductsTab — a product row opens its sheet", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signInWith(["locations:read", "items:read", "items:write"]);
    serveShelf([flour]);
    return () => signOut();
  });

  it("opens the product editor from the sheet's Edit and closes it again", async () => {
    renderTab();
    // The phone card is the last place the name appears.
    const names = await screen.findAllByText("Flour");
    await userEvent.click(names[names.length - 1]);

    const sheet = await screen.findByRole("dialog", { name: "Flour" });
    await userEvent.click(within(sheet).getByRole("button", { name: "Edit" }));

    const editor = await screen.findByRole("dialog", {
      name: "Product editor",
    });
    expect(editor).toHaveTextContent("Editing i-flour");
    expect(
      screen.queryByRole("dialog", { name: "Flour" }),
    ).not.toBeInTheDocument();

    await userEvent.click(
      within(editor).getByRole("button", { name: "Close editor" }),
    );
    expect(
      screen.queryByRole("dialog", { name: "Product editor" }),
    ).not.toBeInTheDocument();
  });

  it("removes a unit from the phone card without opening the product's sheet", async () => {
    const consumed: string[] = [];
    server.use(
      http.patch("/api/v1/items/:id/consume", ({ params }) => {
        consumed.push(String(params.id));
        return HttpResponse.json({ ...flour, quantity: "2" });
      }),
    );
    renderTab();
    await screen.findAllByText("Flour");

    const removers = screen.getAllByRole("button", { name: "Remove" });
    await userEvent.click(removers[removers.length - 1]);

    await waitFor(() => expect(consumed).toEqual(["i-flour"]));
    expect(
      screen.queryByRole("dialog", { name: "Flour" }),
    ).not.toBeInTheDocument();
  });

  it("closes the sheet with its close button, leaving the product untouched", async () => {
    renderTab();
    const names = await screen.findAllByText("Flour");
    await userEvent.click(names[names.length - 1]);

    const sheet = await screen.findByRole("dialog", { name: "Flour" });
    await userEvent.click(within(sheet).getByRole("button", { name: "Close" }));

    expect(
      screen.queryByRole("dialog", { name: "Flour" }),
    ).not.toBeInTheDocument();
    expect(screen.getAllByText("Flour").length).toBeGreaterThan(0);
  });

  it("moves a product to another location through the sheet's Move, and closes the dialog when cancelled", async () => {
    renderTab();
    const names = await screen.findAllByText("Flour");
    await userEvent.click(names[names.length - 1]);

    const sheet = await screen.findByRole("dialog", { name: "Flour" });
    await userEvent.click(within(sheet).getByRole("button", { name: /Move/ }));

    const mover = await screen.findByRole("dialog", { name: "Move" });
    expect(
      screen.queryByRole("dialog", { name: "Flour" }),
    ).not.toBeInTheDocument();
    await userEvent.click(within(mover).getByRole("button", { name: "Close" }));
    expect(
      screen.queryByRole("dialog", { name: "Move" }),
    ).not.toBeInTheDocument();
  });
});

describe("StorageProductsTab — reads that failed", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signInWith(["locations:read", "items:read", "items:write"]);
    return () => signOut();
  });

  it("offers a retry when the products could not be read, and shows them once it works", async () => {
    let failing = true;
    serveShelf([flour]);
    server.use(
      http.get("/api/v1/locations/:id/items", () =>
        failing
          ? HttpResponse.json({ detail: "down" }, { status: 500 })
          : undefined,
      ),
    );
    renderTab();

    const retry = await screen.findByRole("button", { name: "Try again" });
    failing = false;
    await userEvent.click(retry);

    expect((await screen.findAllByText("Flour")).length).toBeGreaterThan(0);
  });
});
