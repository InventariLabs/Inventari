import { useState } from "react";
import { render, screen, waitFor, within } from "@/test/utils";
import { render as renderAt } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import ItemDetailPage from "./ItemDetailPage";
import { signInWith, signOut } from "@/test/auth";
import { onePage } from "@/test/mocks/page";
import { getRecentItems, RECENT_ITEMS_SCOPE } from "@/lib/recentItems";

/** Renders whatever the page puts in the shell header, as ModuleShell does. */
function PageHeaderHost() {
  const [data, setData] = useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
      {data.actions ? (
        <div data-testid="header-actions">{data.actions}</div>
      ) : null}
      <ItemDetailPage />
    </PageHeaderContext.Provider>
  );
}

// The quick actions are gated on these: writing asks `items:write`, and
// deleting asks the narrower `items:delete` the endpoint checks.
beforeEach(() => {
  signInWith(["items:read", "items:write", "items:delete"]);
});

afterEach(() => signOut());

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useParams: () => ({ id: "item-1" }) };
});

let enabledModules: string[] = [];
vi.mock("@/contexts/ModulesContext", async () => {
  const actual = await vi.importActual("@/contexts/ModulesContext");
  return {
    ...actual,
    useEnabledModulesOptional: () => enabledModules,
  };
});

const rack = {
  id: "loc-equipment",
  name: "Server Rack B",
  full_path: "Office Building → Server Room → Server Rack B",
  parent_id: null,
  is_leaf: true,
  context_tag: "equipment",
  organization_id: "org-1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const item = {
  id: "item-1",
  name: "Rack 42U Open Frame",
  brand: "Digitus",
  serial_number: "SN-483699",
  quantity: 1,
  min_quantity: 2,
  purchase_price: 2400,
  weight: 68,
  weight_unit: "kg",
  location_id: rack.id,
  category_id: null,
  description: null,
  added_date: "2026-08-01T00:00:00Z",
  expiry_date: null,
  freeze_date: null,
  shelf_location: null,
  image_url: null,
  metadata: null,
  is_deleted: false,
  organization_id: "org-1",
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

/**
 * `/inventory/items/:id` used to redirect to the list with the action sheet
 * open — a menu of things to do with the record, with no way to link to it,
 * open it in a second tab, or read the fields it was not asked about. The
 * same physical rack had a page when Equipment looked at it and a menu when
 * Inventory did.
 */
describe("ItemDetailPage", () => {
  beforeEach(() => {
    server.use(
      http.get("*/items/item-1", () => HttpResponse.json(item)),
      http.get("*/items/item-1/history", () =>
        HttpResponse.json({
          items: [
            {
              id: "h1",
              item_id: "item-1",
              action: "CREATED",
              created_at: "2026-08-01T09:00:00Z",
              user_name: "Administrator",
              changes: null,
            },
          ],
          next_cursor: null,
          has_more: false,
        }),
      ),
      http.get("*/locations", () => HttpResponse.json(onePage([rack]))),
      http.get("*/stock-moves", () =>
        HttpResponse.json({
          items: [
            {
              id: "m1",
              organization_id: "org-1",
              product_template_id: "tpl-1",
              from_location_id: null,
              to_location_id: rack.id,
              quantity: "1.000",
              lot_id: null,
              state: "done",
              reference_type: "document",
              reference_id: "doc-1",
              created_by: "u1",
              created_at: "2026-08-02T09:00:00Z",
              updated_at: null,
              completed_at: "2026-08-02T09:00:00Z",
              product_name: "Rack 42U Open Frame",
              uom_symbol: "pcs",
              from_location_name: null,
              to_location_name: "Server Rack B",
              lot_name: null,
              user_name: "Hanna Kowal",
            },
          ],
          total: 1,
          limit: 20,
          offset: 0,
          has_more: false,
        }),
      ),
    );
    enabledModules = [];
  });

  it("is remembered in Recently visited, under its own address", async () => {
    // The launcher's panel and the command palette read this list; nothing
    // wrote to it, so both stayed empty however many products were opened.
    localStorage.clear();
    renderAt(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <MemoryRouter initialEntries={["/inventory/items/item-1"]}>
          <ModulesProvider>
            <PageHeaderContext.Provider
              value={{ data: {}, setHeader: () => {} }}
            >
              <ItemDetailPage />
            </PageHeaderContext.Provider>
          </ModulesProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await screen.findByText("Digitus");
    expect(getRecentItems("current-user", RECENT_ITEMS_SCOPE)).toEqual([
      expect.objectContaining({
        id: "item-1",
        title: "Rack 42U Open Frame",
        module: "inventory",
        path: "/inventory/items/item-1",
      }),
    ]);
  });

  it("reads out the record, including the fields the sheet never showed", async () => {
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemDetailPage />
      </PageHeaderContext.Provider>,
    );

    expect(await screen.findByText("Digitus")).toBeInTheDocument();
    expect(screen.getByText("SN-483699")).toBeInTheDocument();
    // The name lives in the page header, so the body does not repeat it.
    expect(screen.queryByText("Product name")).toBeNull();
  });

  it("names the location even when the general lists hide it", async () => {
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemDetailPage />
      </PageHeaderContext.Provider>,
    );

    await screen.findByText("Digitus");
    await waitFor(() =>
      expect(screen.getByText(/Server Rack B/)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/^Unknown$/i)).toBeNull();
  });

  it("leaves out a field the record does not carry", async () => {
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemDetailPage />
      </PageHeaderContext.Provider>,
    );

    await screen.findByText("Digitus");
    // No expiry date on this record — the label must not appear at all,
    // because a column of empty rows buries the handful that have values.
    expect(screen.queryByText("Expiry date")).toBeNull();
  });

  it("shows the history on its own tab", async () => {
    const user = userEvent.setup();
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemDetailPage />
      </PageHeaderContext.Provider>,
    );

    await screen.findByText("Digitus");
    await user.click(screen.getByRole("tab", { name: /history/i }));

    expect(await screen.findByText(/Administrator/)).toBeInTheDocument();
  });

  it("says so when the record is gone", async () => {
    server.use(
      http.get("*/items/item-1", () =>
        HttpResponse.json({ detail: "Not found" }, { status: 404 }),
      ),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemDetailPage />
      </PageHeaderContext.Provider>,
    );

    expect(
      await screen.findByText(/no longer exists|no access/i),
    ).toBeInTheDocument();
  });

  it("points at the archive when the product is there, not nowhere", async () => {
    // A soft-deleted product got "this product no longer exists"
    // from the screen that is one click away from the archive holding it.
    // The 404 carries ITEM_ARCHIVED, so the page says where it went.
    server.use(
      http.get("*/items/item-1", () =>
        HttpResponse.json(
          {
            detail: {
              code: "ITEM_ARCHIVED",
              message: "Item is archived and can be restored from the archive",
            },
          },
          { status: 404 },
        ),
      ),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemDetailPage />
      </PageHeaderContext.Provider>,
    );

    expect(await screen.findByText(/in the archive/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /open the archive/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/no longer exists/i)).not.toBeInTheDocument();
  });
  it("carries the fields the edit form asks about", async () => {
    // The page showed six values while the edit modal of the same record
    // offered more than fifteen — a reader who wanted to know the threshold
    // had to open a form built for changing it.
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemDetailPage />
      </PageHeaderContext.Provider>,
    );

    await screen.findByText("Digitus");
    expect(screen.getByText("Low-stock threshold")).toBeInTheDocument();
    expect(screen.getByText("Net weight")).toBeInTheDocument();
    expect(screen.getByText("68 kg")).toBeInTheDocument();
  });

  it("offers the actions the sheet over the list offers", async () => {
    // Before this the page's only verb was "Edit", so the shortcut could do
    // more to the record than the record's own address could.
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemDetailPage />
      </PageHeaderContext.Provider>,
    );

    await screen.findByText("Digitus");
    expect(
      screen.getByRole("button", { name: "Remove 1 unit" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Add 1 unit" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Move" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("hides Edit and every quick action from a read-only account", async () => {
    // The header's Edit was the fourth door into `ItemEditModal` and the
    // only one that never asked; a viewer filled in the form and met the
    // 403 at Save.
    signInWith(["items:read"]);
    render(<PageHeaderHost />);

    await screen.findByText("Digitus");
    expect(
      screen.queryByRole("button", { name: "Edit" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Move" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Delete" }),
    ).not.toBeInTheDocument();
  });

  it("hides Delete from a writer without items:delete, and keeps Edit", async () => {
    // The endpoint distinguishes `items:write` from `items:delete`; the
    // discard action was offered on the strength of the first.
    signInWith(["items:read", "items:write"]);
    render(<PageHeaderHost />);

    await screen.findByText("Digitus");
    expect(
      await screen.findByRole("button", { name: "Edit" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Delete" }),
    ).not.toBeInTheDocument();
  });

  /**
   * The record's audit trail and the place's movement ledger are two
   * different questions, and the page used to answer only the first.
   */
  it("offers the movements of the product in this place", async () => {
    enabledModules = ["warehouse"];
    server.use(
      http.get("*/items/item-1", () =>
        HttpResponse.json({ ...item, template_id: "tpl-1" }),
      ),
    );
    const user = userEvent.setup();
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemDetailPage />
      </PageHeaderContext.Provider>,
    );

    await screen.findByText("Digitus");
    await user.click(screen.getByRole("tab", { name: /movements/i }));

    // Both renderings sit in the DOM under jsdom -- the desktop/phone split
    // is a media query -- so this asks the table.
    const table = await screen.findByRole("table");
    expect(within(table).getByText(/Hanna Kowal/)).toBeInTheDocument();
    // Not "this record's history": one place can hold two records of the
    // same product, and a movement names the product, not the row.
    expect(within(table).getByText(/Server Rack B/)).toBeInTheDocument();
  });

  it("hides the movements tab where nothing records movements", async () => {
    enabledModules = [];
    server.use(
      http.get("*/items/item-1", () =>
        HttpResponse.json({ ...item, template_id: "tpl-1" }),
      ),
    );
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemDetailPage />
      </PageHeaderContext.Provider>,
    );

    await screen.findByText("Digitus");
    // A household writes no StockMove at all -- the tab could only ever open
    // an empty screen (ADR-004).
    expect(screen.queryByRole("tab", { name: /movements/i })).toBeNull();
  });

  it("hides the movements tab for a record with no product behind it", async () => {
    enabledModules = ["warehouse"];
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemDetailPage />
      </PageHeaderContext.Provider>,
    );

    await screen.findByText("Digitus");
    expect(screen.queryByRole("tab", { name: /movements/i })).toBeNull();
  });
});
