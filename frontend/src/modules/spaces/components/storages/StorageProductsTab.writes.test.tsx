import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";

import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import type { StorageLocation, StorageLocationSummary } from "@/types";

import { StorageProductsTab } from "./StorageProductsTab";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const storage = {
  id: "shelf-1",
  name: "Shelf 1",
  location_type: { behavior_mode: "STANDARD" },
} as unknown as StorageLocation;
const summary = {
  id: "shelf-1",
  name: "Shelf 1",
  full_path: "Shelf 1",
  direct_children_count: 0,
} as StorageLocationSummary;

function product(
  id: string,
  name: string,
  extra: Record<string, unknown> = {},
) {
  return {
    id,
    name,
    location_id: "shelf-1",
    category_id: null,
    quantity: "3",
    added_date: "2026-01-01",
    expiry_date: null,
    freeze_date: null,
    shelf_location: null,
    is_deleted: false,
    created_at: "2026-01-01T00:00:00",
    updated_at: "2026-01-01T00:00:00",
    ...extra,
  };
}

let shelfItems: ReturnType<typeof product>[];

beforeEach(() => {
  shelfItems = [
    product("item-1", "Apple Juice", { category_id: "cat-1" }),
    product("item-2", "Loose screws"),
  ];
  server.use(
    http.get("/api/v1/locations/shelf-1/items", () =>
      HttpResponse.json(onePage(shelfItems)),
    ),
    http.get("/api/v1/categories", () =>
      HttpResponse.json(
        onePage([{ id: "cat-1", name: "Drinks", code: null, icon: null }]),
      ),
    ),
  );
});

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <StorageProductsTab
          storage={storage}
          summary={summary}
          isArchived={false}
          canWriteItems
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const rowOf = (name: string) =>
  screen.getAllByText(name)[0].closest("tr") as HTMLElement;

/**
 * Removing one unit from a row and deleting a row are the two writes on this
 * tab. What the reader must be told differs by the answer — the last unit
 * gone, or how many remain — and a delete must wait for its confirmation.
 */
describe("StorageProductsTab — taking stock off the shelf", () => {
  it("says how much is left after one unit is consumed", async () => {
    let body: Record<string, unknown> = {};
    server.use(
      http.patch("/api/v1/items/item-1/consume", async ({ request }) => {
        body = (await request.json()) as typeof body;
        return HttpResponse.json({
          ...product("item-1", "Apple Juice"),
          quantity: "2",
          uom: { symbol: "pcs", rounding: 1 },
        });
      }),
    );
    const user = userEvent.setup();
    renderTab();

    await screen.findAllByText("Apple Juice");
    await user.click(
      within(rowOf("Apple Juice")).getByRole("button", { name: "Remove" }),
    );
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "Removed 1 unit — 2 pcs. left",
      ),
    );
    expect(body).toMatchObject({ quantity: 1, reason: "USED" });
  });

  it("says the product is used up when the last unit goes", async () => {
    server.use(
      http.patch("/api/v1/items/item-1/consume", () =>
        HttpResponse.json({
          ...product("item-1", "Apple Juice"),
          quantity: "0",
        }),
      ),
    );
    const user = userEvent.setup();
    renderTab();

    await screen.findAllByText("Apple Juice");
    await user.click(
      within(rowOf("Apple Juice")).getByRole("button", { name: "Remove" }),
    );
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Success"));
  });

  it("passes on why a consume was refused", async () => {
    server.use(
      http.patch("/api/v1/items/item-1/consume", () =>
        HttpResponse.json({ detail: "Nothing left to take" }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    renderTab();

    await screen.findAllByText("Apple Juice");
    await user.click(
      within(rowOf("Apple Juice")).getByRole("button", { name: "Remove" }),
    );
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Nothing left to take"),
    );
  });

  it("deletes a product only after the confirmation", async () => {
    const deleted = vi.fn();
    server.use(
      http.delete("/api/v1/items/item-2", () => {
        deleted();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderTab();

    await screen.findAllByText("Loose screws");
    await user.click(
      within(rowOf("Loose screws")).getByRole("button", { name: "Delete" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    expect(
      within(dialog).getByText("Are you sure you want to delete this product?"),
    ).toBeInTheDocument();
    expect(deleted).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleted).toHaveBeenCalledTimes(1));
  });
});

/**
 * A category filter that outlives its last product would show an empty
 * shelf that is not empty. The tab switches it off and says why.
 */
describe("StorageProductsTab — the category filter", () => {
  it("narrows to the chosen category, and lets go of it when the category leaves the shelf", async () => {
    server.use(
      http.delete("/api/v1/items/item-1", () => {
        shelfItems = shelfItems.filter((item) => item.id !== "item-1");
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderTab();

    await screen.findAllByText("Loose screws");
    await user.click(screen.getByRole("button", { name: /Drinks/ }));
    await waitFor(() =>
      expect(screen.queryAllByText("Loose screws")).toHaveLength(0),
    );

    await user.click(
      within(rowOf("Apple Juice")).getByRole("button", { name: "Delete" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(toast.info).toHaveBeenCalledWith(
        "The category filter was switched off — nothing on this shelf is in it any more",
      ),
    );
    expect((await screen.findAllByText("Loose screws")).length).toBeGreaterThan(
      0,
    );
  });
});
