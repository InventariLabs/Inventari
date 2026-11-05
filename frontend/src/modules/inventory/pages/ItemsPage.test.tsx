import { render, screen, fireEvent, waitFor, within } from "@/test/utils";
import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { useState } from "react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse, delay } from "msw";
import { server } from "@/test/mocks/server";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render as rtlRender } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import i18n from "@/i18n/config";
import { ModulesProvider } from "@/contexts/ModulesContext";
import ItemsPage from "./ItemsPage";
import { signInWith, signOut } from "@/test/auth";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { onePage } from "@/test/mocks/page";
import { serveLocations } from "@/test/serveLocations";

// Every action under test here writes; without the permission the page
// renders its read-only self and describes a different screen. Deleting asks
// the narrower `items:delete`, which the endpoint checks.
beforeEach(() => {
  signInWith(["items:read", "items:write", "items:delete"]);
});

afterEach(() => signOut());

// jsdom's window.location is a static mock here, so navigation is asserted
// through the navigate spy instead of the address bar.
const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => mockNavigate };
});

describe("ItemsPage", () => {
  beforeEach(() => {
    // Mock desktop view by default for these tests
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation((query) => ({
        matches: query === "(min-width: 1024px)",
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  it("should render items list", async () => {
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );

    // Should find at least one instance of the test item
    const items = await screen.findAllByText(/Test Item/i);
    expect(items.length).toBeGreaterThan(0);
  });

  it("should filter items by search", async () => {
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );

    const searchInput = await screen.findByPlaceholderText(/Search products…/i);
    fireEvent.change(searchInput, { target: { value: "Non-existent" } });

    await waitFor(() => {
      const items = screen.queryAllByText(/Test Item/i);
      expect(items.length).toBe(0);
    });
  });

  describe("a row's own actions", () => {
    const row = (id: string, name: string) => ({
      id,
      name,
      quantity: 1,
      unit: "pcs",
      category_id: "1",
      location_id: "1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });
    const rows = [row("a", "Alpha"), row("b", "Beta")];

    // Two rows, so an action that reached the wrong record cannot pass.
    beforeEach(() => {
      server.use(
        http.get("/api/v1/items", () =>
          HttpResponse.json({ items: rows, total: rows.length }),
        ),
        http.get("/api/v1/items/:id", ({ params }) =>
          HttpResponse.json(rows.find((r) => r.id === params.id)),
        ),
      );
    });

    const openRow = async (name: string) => {
      render(
        <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
          <ItemsPage />
        </PageHeaderContext.Provider>,
      );
      return (await screen.findByText(name)).closest("tr") as HTMLElement;
    };

    it("deletes the record of the row, once the reader says why", async () => {
      const user = userEvent.setup();
      const deleted: unknown[] = [];
      server.use(
        http.delete("/api/v1/items/:id", async ({ params, request }) => {
          deleted.push({
            id: params.id,
            ...((await request.json()) as object),
          });
          return new HttpResponse(null, { status: 204 });
        }),
      );

      const beta = await openRow("Beta");
      await user.click(within(beta).getByRole("button", { name: "Delete" }));

      const dialog = await screen.findByRole("alertdialog");
      expect(deleted).toEqual([]);

      await user.selectOptions(
        within(dialog).getByTestId("deletion-reason"),
        "EXPIRED",
      );
      await user.click(within(dialog).getByRole("button", { name: "Delete" }));

      await waitFor(() =>
        expect(deleted).toEqual([
          expect.objectContaining({ id: "b", reason: "EXPIRED" }),
        ]),
      );
    });

    it("edits the record of the row and saves it there", async () => {
      const user = userEvent.setup();
      const saved: unknown[] = [];
      server.use(
        http.put("/api/v1/items/:id", async ({ params, request }) => {
          const body = (await request.json()) as { name?: string };
          saved.push({ id: params.id, name: body.name });
          return HttpResponse.json({ ...rows[1], ...body });
        }),
      );

      const beta = await openRow("Beta");
      await user.click(within(beta).getByRole("button", { name: "Edit" }));

      expect(await screen.findByText(/Edit product/i)).toBeInTheDocument();
      const name = await screen.findByDisplayValue("Beta");
      await user.clear(name);
      await user.type(name, "Beta renamed");
      await user.click(screen.getByRole("button", { name: /Save changes/i }));

      await waitFor(() =>
        expect(saved).toEqual([{ id: "b", name: "Beta renamed" }]),
      );
    });
  });

  it("opens the product dialog when the product's name is clicked", async () => {
    const user = userEvent.setup();
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );

    await user.click(await screen.findByTestId("item-name"));

    // The pencil's own dialog, not a sheet of quick actions in front of it.
    expect(await screen.findByText(/Edit product/i)).toBeInTheDocument();
    expect(await screen.findByDisplayValue("Test Item")).toBeInTheDocument();
  });
});

describe("ItemsPage — module-owned data is an organization policy", () => {
  const org = {
    id: "org-1",
    name: "Test Org",
    currency: "PLN",
    created_at: "2026-01-01T00:00:00Z",
    created_by: null,
    enabled_modules: ["core", "items"],
  };

  function captureItemsRequests(settings: Record<string, unknown>) {
    const seen: URL[] = [];
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({ ...org, settings }),
      ),
      http.get("*/items", ({ request }) => {
        seen.push(new URL(request.url));
        return HttpResponse.json({ items: [], total: 0 });
      }),
    );
    return seen;
  }

  it("asks the API to hide module data while the organization has not opted in", async () => {
    const seen = captureItemsRequests({});
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );

    await waitFor(() => expect(seen.length).toBeGreaterThan(0));
    // The list itself asks for the filtered view; the hidden-data probe may
    // follow it unfiltered, so the assertion is on the list's own request.
    expect(
      seen.some(
        (u) => u.searchParams.get("exclude_module_contexts") === "true",
      ),
    ).toBe(true);
  });

  it("stops hiding it once the organization opts in", async () => {
    const seen = captureItemsRequests({ show_module_data: true });
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );

    await waitFor(() =>
      expect(
        seen.some(
          (u) => u.searchParams.get("exclude_module_contexts") === "false",
        ),
      ).toBe(true),
    );
  });

  it("names hidden module data instead of an empty list", async () => {
    // The filtered answer is empty, the unfiltered one is not: the list owes
    // the reader where the rows went, not "No products" over rows that
    // plainly exist.
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({ ...org, settings: {} }),
      ),
      http.get("*/items", ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get("exclude_module_contexts") === "false")
          return HttpResponse.json({
            items: [{ id: "i1", name: "QA Item" }],
            total: 1,
          });
        return HttpResponse.json({ items: [], total: 0 });
      }),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );

    expect(
      await screen.findByText("Some products are hidden"),
    ).toBeInTheDocument();
    expect(screen.queryByText("No products")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /open settings/i }),
    ).toBeInTheDocument();
  });

  it("keeps the counter above a list that still has rows", async () => {
    // The counter belonged to the empty state alone: the first visible row
    // silenced it, and two hidden products behind two visible ones said
    // nothing at all. The switch it points at is an administrator's.
    signInWith(["items:read", "items:write", "admin:access"]);
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({ ...org, settings: {} }),
      ),
      http.get("*/items", ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get("exclude_module_contexts") === "false")
          return HttpResponse.json({
            items: [
              { id: "i1", name: "QA Item" },
              { id: "i2", name: "QA Item 2" },
            ],
            total: 4,
          });
        return HttpResponse.json({
          items: [
            { id: "i3", name: "Visible Item" },
            { id: "i4", name: "Visible Item 2" },
          ],
          total: 2,
        });
      }),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );

    expect(await screen.findByText("Visible Item")).toBeInTheDocument();
    expect(screen.getByText(/2 products are hidden/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /open settings/i }),
    ).toBeInTheDocument();
  });

  it("says the list counts records, not products", async () => {
    // A tin on three shelves is three rows, so "587 results" for 116
    // products read ten times too big to an owner asking how many they carry.
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({ ...org, settings: {} }),
      ),
      http.get("*/items", () =>
        HttpResponse.json({
          items: [
            { id: "i1", name: "Tuna in Oil" },
            { id: "i2", name: "Tuna in Oil" },
          ],
          total: 587,
        }),
      ),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );

    expect(await screen.findByText("587 records")).toBeInTheDocument();
  });

  it("names the products beside the records, the unit a shortage is counted in", async () => {
    // The running-low tile says 3 and opens 6 rows: a list that said only
    // "6 records" left the reader to work out that both were right.
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({ ...org, settings: {} }),
      ),
      http.get("*/items", () =>
        HttpResponse.json({
          items: [{ id: "i1", name: "Tuna in Oil" }],
          total: 6,
        }),
      ),
      http.get("*/items/aggregates", () =>
        HttpResponse.json({
          count: 6,
          product_count: 3,
          total_weight: 0,
          total_volume: 0,
          total_value: null,
          value_source: "purchase_price",
          unpriced_count: 0,
        }),
      ),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );

    expect(
      await screen.findByText("6 records · 3 products"),
    ).toBeInTheDocument();
  });

  it("states no count while the list request has failed", async () => {
    // Zero answers "how many are there", and with the request down there is
    // no answer: the bar used to say "0 records" beside "An error occurred".
    // The bar is there once the reader has narrowed the list, so the search
    // is what makes the request fail.
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({ ...org, settings: {} }),
      ),
      http.get("*/items", ({ request }) =>
        new URL(request.url).searchParams.get("search")
          ? HttpResponse.json({ detail: "bad" }, { status: 422 })
          : HttpResponse.json({
              items: [{ id: "i1", name: "Tuna in Oil" }],
              total: 1,
            }),
      ),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );
    expect(await screen.findByText("1 record")).toBeInTheDocument();

    fireEvent.change(await screen.findByPlaceholderText(/Search products…/i), {
      target: { value: "zz" },
    });

    expect(await screen.findByText(/an error occurred/i)).toBeInTheDocument();
    expect(screen.queryByText(/\b0 records/)).toBeNull();
  });

  it("shows no hidden counter when nothing is kept out", async () => {
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({ ...org, settings: {} }),
      ),
      http.get("*/items", () =>
        HttpResponse.json({
          items: [{ id: "i3", name: "Visible Item" }],
          total: 1,
        }),
      ),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );

    expect(await screen.findByText("Visible Item")).toBeInTheDocument();
    expect(screen.queryByText(/products are hidden/)).toBeNull();
  });

  /**
   * The two halves of this screen used to answer differently: `/items` hides
   * an item by its *category* tag, `/locations` hides a location by its own —
   * so an unclaimed item put away on an equipment rack stayed in the list
   * while the rack it names disappeared from the lookup, and 83 rows read
   * "Unknown" over a perfectly good location.
   */
  it("names the location of a row it decided to show", async () => {
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

    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({ ...org, settings: {} }),
      ),
      http.get("*/locations", ({ request }) => {
        const url = new URL(request.url);
        // What the organization policy keeps out of the general lists.
        if (url.searchParams.get("exclude_module_contexts") === "true")
          return HttpResponse.json(onePage([]));
        return HttpResponse.json(onePage([rack]));
      }),
      http.get("*/items", () =>
        HttpResponse.json({
          items: [
            {
              id: "item-1",
              name: "Rack 42U Open Frame",
              quantity: 1,
              location_id: rack.id,
              organization_id: "org-1",
              created_at: "2026-01-01T00:00:00Z",
              updated_at: "2026-01-01T00:00:00Z",
            },
          ],
          total: 1,
        }),
      ),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );

    await screen.findByText("Rack 42U Open Frame");
    await waitFor(() =>
      expect(screen.getByText(/Server Rack B/)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/^Unknown$/i)).toBeNull();
  });

  /**
   * A row is not "Unknown" for as long as the places that name it are on
   * their way: the page, which knows the answer is pending, hands the rows
   * nothing to look the place up in.
   */
  it("prints no place on a row while the places are still loading", async () => {
    let release = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({ ...org, settings: {} }),
      ),
      http.get("*/locations", async () => {
        await gate;
        await delay(0);
        return HttpResponse.json(
          onePage([
            {
              id: "loc-late",
              name: "Late Shelf",
              parent_id: null,
              is_leaf: true,
              organization_id: "org-1",
              created_at: "2026-01-01T00:00:00Z",
              updated_at: "2026-01-01T00:00:00Z",
            },
          ]),
        );
      }),
      http.get("*/items", () =>
        HttpResponse.json({
          items: [
            {
              id: "item-1",
              name: "Plum Butter",
              quantity: 1,
              location_id: "loc-late",
              organization_id: "org-1",
              created_at: "2026-01-01T00:00:00Z",
              updated_at: "2026-01-01T00:00:00Z",
            },
          ],
          total: 1,
        }),
      ),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );

    await screen.findByText("Plum Butter");
    expect(screen.queryByText(/^Unknown$/i)).toBeNull();
    release();
    await waitFor(() =>
      expect(screen.getAllByText(/Late Shelf/).length).toBeGreaterThan(0),
    );
    expect(screen.queryByText(/^Unknown$/i)).toBeNull();
  });

  /**
   * A warehouse of two thousand shelves: the screen used to download all of
   * them, page after page and twice over, to name the dozen on screen and to
   * fill a filter. It names the places its rows stand in and searches for the
   * rest.
   */
  it("names the rows' places and searches the filter without reading the catalogue", async () => {
    const shelves = Array.from({ length: 2000 }, (_, i) => ({
      id: `shelf-${i}`,
      name: `Shelf ${i}`,
      parent_id: "wh",
    }));
    const requests = serveLocations([
      { id: "wh", name: "Main warehouse", parent_id: null },
      ...shelves,
    ]);
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({ ...org, settings: {} }),
      ),
      http.get("*/items", () =>
        HttpResponse.json({
          items: [
            {
              id: "item-1",
              name: "Bolts M8",
              quantity: 1,
              location_id: "shelf-1999",
              organization_id: "org-1",
              created_at: "2026-01-01T00:00:00Z",
              updated_at: "2026-01-01T00:00:00Z",
            },
          ],
          total: 1,
        }),
      ),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );

    await screen.findByText("Bolts M8");
    await waitFor(() =>
      expect(screen.getAllByText(/Shelf 1999/).length).toBeGreaterThan(0),
    );
    fireEvent.click(screen.getByRole("button", { name: /filter|filtr/i }));
    fireEvent.click(
      screen.getByRole("combobox", { name: /location|lokalizacj/i }),
    );
    fireEvent.change(await screen.findByPlaceholderText("Search"), {
      target: { value: "Shelf 1234" },
    });
    expect(
      await screen.findByRole("button", { name: /Shelf 1234/ }),
    ).toBeInTheDocument();

    // Every ask is a page of the places wanted, none a walk over all 2 001.
    expect(requests.length).toBeGreaterThan(0);
    expect(requests.every((r) => Number(r.get("limit")) <= 100)).toBe(true);
    expect(
      requests.every((r) => !r.get("offset") || r.get("offset") === "0"),
    ).toBe(true);
    expect(requests.some((r) => r.getAll("ids").includes("shelf-1999"))).toBe(
      true,
    );
  });

  /**
   * The filter, unlike the naming above, is a choice — and a choice the
   * organization said it did not want to be offered.
   */
  it("keeps module-owned locations out of the filter it offers", async () => {
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({ ...org, settings: {} }),
      ),
      http.get("*/locations", ({ request }) => {
        const url = new URL(request.url);
        const scoped =
          url.searchParams.get("exclude_module_contexts") === "true";
        return HttpResponse.json(
          onePage([
            {
              id: "loc-shelf",
              name: "Shelf A",
              full_path: "Shelf A",
              parent_id: null,
              is_leaf: true,
              organization_id: "org-1",
              created_at: "2026-01-01T00:00:00Z",
              updated_at: "2026-01-01T00:00:00Z",
            },
            ...(scoped
              ? []
              : [
                  {
                    id: "loc-equipment",
                    name: "Server Rack B",
                    full_path: "Server Rack B",
                    parent_id: null,
                    is_leaf: true,
                    context_tag: "equipment",
                    organization_id: "org-1",
                    created_at: "2026-01-01T00:00:00Z",
                    updated_at: "2026-01-01T00:00:00Z",
                  },
                ]),
          ]),
        );
      }),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );
    await screen.findAllByText(/Test Item/i);
    fireEvent.click(screen.getByRole("button", { name: /filter|filtr/i }));
    fireEvent.click(
      screen.getByRole("combobox", { name: /location|lokalizacj/i }),
    );

    expect(
      await screen.findByRole("button", { name: /^Shelf A$/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Server Rack B$/ }),
    ).toBeNull();
  });

  /**
   * The same question for the other picker in the same panel. The rows
   * obeyed the policy and the location filter obeyed it; the category filter
   * went on offering the equipment categories whose rows had just been
   * hidden, so choosing one narrowed the list to nothing.
   */
  it("keeps module-owned categories out of the filter it offers", async () => {
    const category = (id: string, name: string, contextTag?: string) => ({
      id,
      name,
      organization_id: "org-1",
      context_tag: contextTag ?? null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });

    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({ ...org, settings: {} }),
      ),
      http.get("*/categories", ({ request }) => {
        const url = new URL(request.url);
        const scoped =
          url.searchParams.get("exclude_module_contexts") === "true";
        return HttpResponse.json(
          onePage([
            category("cat-food", "Cold cuts"),
            ...(scoped ? [] : [category("cat-laptop", "Laptop", "equipment")]),
          ]),
        );
      }),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );
    await screen.findAllByText(/Test Item/i);
    fireEvent.click(screen.getByRole("button", { name: /filter|filtr/i }));
    fireEvent.click(
      screen.getByRole("combobox", {
        name: /^category$|^kategoria$|^kategorie$/i,
      }),
    );

    expect(
      await screen.findByRole("button", { name: /^Cold cuts$/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Laptop$/ })).toBeNull();
  });

  it("offers them again once the organization opts in", async () => {
    const category = (id: string, name: string, contextTag?: string) => ({
      id,
      name,
      organization_id: "org-1",
      context_tag: contextTag ?? null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });

    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({ ...org, settings: { show_module_data: true } }),
      ),
      http.get("*/categories", () =>
        HttpResponse.json(
          onePage([
            category("cat-food", "Cold cuts"),
            category("cat-laptop", "Laptop", "equipment"),
          ]),
        ),
      ),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );
    await screen.findAllByText(/Test Item/i);
    fireEvent.click(screen.getByRole("button", { name: /filter|filtr/i }));
    fireEvent.click(
      screen.getByRole("combobox", {
        name: /^category$|^kategoria$|^kategorie$/i,
      }),
    );

    expect(
      await screen.findByRole("button", { name: /^Laptop$/ }),
    ).toBeInTheDocument();
  });
});

/**
 * The location and category filters were native `<select>`s holding
 * 177 and 76 entries — no way to search, and no way to see where you were in
 * the list. The module already ships a searchable picker for the item form.
 */
describe("ItemsPage — filter panel", () => {
  beforeEach(() => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation((query) => ({
        matches: query === "(min-width: 1024px)",
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  const openFilters = async () => {
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );
    await screen.findAllByText(/Test Item/i);
    fireEvent.click(screen.getByRole("button", { name: /filter|filtr/i }));
  };

  it("lets the location list be searched rather than scrolled", async () => {
    server.use(
      // The server answers the search: only what contains what was typed.
      http.get("/api/v1/locations", ({ request }) => {
        const q = (
          new URL(request.url).searchParams.get("q") ?? ""
        ).toLowerCase();
        return HttpResponse.json(
          onePage(
            ["Cold Storage", "Receiving", "Shelf A"]
              .filter((name) => name.toLowerCase().includes(q))
              .map((name, i) => ({
                id: String(i + 1),
                name,
                parent_id: null,
                is_leaf: true,
                organization_id: "org1",
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
              })),
          ),
        );
      }),
    );

    await openFilters();

    fireEvent.click(
      screen.getByRole("combobox", { name: /location|lokalizacj/i }),
    );

    const search = await screen.findByPlaceholderText("Search");
    fireEvent.change(search, { target: { value: "Receiv" } });

    // Only the matching location survives the search
    fireEvent.click(await screen.findByRole("button", { name: /^Receiving$/ }));
    expect(screen.queryByRole("button", { name: /^Shelf A$/ })).toBeNull();

    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: /location|lokalizacj/i }),
      ).toHaveTextContent("Receiving"),
    );
  });

  it("lets the category list be searched rather than scrolled", async () => {
    await openFilters();

    fireEvent.click(
      screen.getByRole("combobox", {
        name: /^category$|^kategoria$|^kategorie$/i,
      }),
    );

    const search = await screen.findByPlaceholderText("Search");
    fireEvent.change(search, { target: { value: "Drink" } });

    // Only the matching category survives the filter
    expect(screen.queryByRole("button", { name: /^Food$/ })).toBeNull();
    expect(
      await screen.findByRole("button", { name: /^Drinks$/ }),
    ).toBeInTheDocument();
  });
});

/**
 * the header actions row hugs the right edge, the primary CTA is a
 * real button (UI_GUIDELINES §11.3 forbids wrapping it in <Link>), and
 * "Categories" appears exactly once per viewport — the module nav owns it on
 * desktop, the mobile overflow sheet owns it below `sm`.
 */
describe("ItemsPage — header actions", () => {
  beforeEach(() => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation((query) => ({
        matches: query === "(min-width: 1024px)",
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  function renderWithHeader() {
    function Harness() {
      const [header, setHeader] = useState<PageHeaderData>({});
      return (
        <PageHeaderContext.Provider value={{ data: header, setHeader }}>
          <div data-testid="page-header">{header.actions}</div>
          <ItemsPage />
        </PageHeaderContext.Provider>
      );
    }
    return render(<Harness />);
  }

  it("right-aligns the header actions instead of leaving a gap", async () => {
    renderWithHeader();
    await screen.findAllByText(/Test Item/i);

    const header = screen.getByTestId("page-header");
    const cta = within(header).getByRole("button", { name: /add product/i });
    expect(cta.parentElement).toHaveClass("justify-end");
    expect(cta.parentElement).not.toHaveClass("ml-auto");
  });

  it("navigates via a real button, not a <Link>-wrapped one", async () => {
    renderWithHeader();
    await screen.findAllByText(/Test Item/i);

    const header = screen.getByTestId("page-header");
    const cta = within(header).getByRole("button", { name: /add product/i });
    expect(cta.closest("a")).toBeNull();

    fireEvent.click(cta);
    expect(mockNavigate).toHaveBeenCalledWith("/inventory/items/add");
  });

  it("shows Categories once per viewport: sheet on mobile, never the desktop header", async () => {
    renderWithHeader();
    await screen.findAllByText(/Test Item/i);

    const header = screen.getByTestId("page-header");
    expect(
      within(header).queryByRole("button", { name: /categories/i }),
    ).toBeNull();
    expect(
      within(header).queryByRole("link", { name: /categories/i }),
    ).toBeNull();

    fireEvent.click(within(header).getByRole("button", { name: /more/i }));
    const sheet = await screen.findByRole("dialog", { name: /more/i });
    expect(
      within(sheet).getByRole("button", { name: /categories/i }),
    ).toBeInTheDocument();
    expect(
      within(sheet)
        .getByRole("button", { name: /categories/i })
        .closest("a"),
    ).toBeNull();
  });
});

describe("ItemsPage — bulk selection", () => {
  beforeEach(() => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation((query) => ({
        matches: query === "(min-width: 1024px)",
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  it("deletes every selected row, and only those", async () => {
    // The old guard selected one row and stopped at "a dialog opened", so a
    // bulk delete that dropped rows — or deleted the wrong ones — would have
    // passed it.
    const deleted: string[] = [];
    server.use(
      http.get("/api/v1/items", () =>
        HttpResponse.json({
          items: [
            {
              id: "a",
              name: "Alpha",
              quantity: 1,
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            },
            {
              id: "b",
              name: "Beta",
              quantity: 1,
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            },
            {
              id: "c",
              name: "Gamma",
              quantity: 1,
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            },
          ],
          total: 3,
        }),
      ),
      http.delete("/api/v1/items/:id", ({ params }) => {
        deleted.push(String(params.id));
        return new HttpResponse(null, { status: 204 });
      }),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );
    await screen.findAllByText("Alpha");

    const checkboxes = screen.getAllByRole("checkbox");
    // [0] is the header's select-all; pick the first two rows
    fireEvent.click(checkboxes[1]);
    fireEvent.click(checkboxes[2]);

    const bar = await screen.findByRole("toolbar", {
      name: /selected|zaznacz/i,
    });
    fireEvent.click(within(bar).getByRole("button", { name: /delete|usuń/i }));

    // The confirm step is a plain overlay, not a role="dialog" — find its
    // button among the two that now read "Delete".
    const confirmButtons = await screen.findAllByRole("button", {
      name: /^delete$|^usuń$/i,
    });
    fireEvent.click(confirmButtons[confirmButtons.length - 1]);

    await waitFor(() => expect(deleted.length).toBe(2));
    expect(deleted.sort()).toEqual(["a", "b"]);
  });

  it("offers actions once rows are selected", async () => {
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );
    await screen.findAllByText(/Test Item/i);

    const checkboxes = screen.getAllByRole("checkbox");
    // The first checkbox is the header's select-all
    fireEvent.click(checkboxes[1]);

    const bar = await screen.findByRole("toolbar", {
      name: /selected|zaznacz/i,
    });
    expect(bar).toBeInTheDocument();

    fireEvent.click(within(bar).getByRole("button", { name: /edit|edytuj/i }));

    await waitFor(() => {
      expect(
        screen.getByRole("dialog", { name: /bulk edit|edycja/i }),
      ).toBeInTheDocument();
    });
  });
});

/**
 * sort and the result count used to occupy two bands of their own
 * below the bar. The bar already had slots for both — they just were not
 * used. This test pins the sort select and the counter inside the bar so the
 * page does not grow the bands back.
 */
describe("ItemsPage — control bar layout", () => {
  beforeEach(() => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation((query) => ({
        matches: query === "(min-width: 1024px)",
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  it("keeps the sort control and the result count inside the bar", async () => {
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );
    await screen.findAllByText(/Test Item/i);

    const search = screen.getByTestId("list-search-input");
    const sort = screen.getByRole("combobox", { name: /^sort$/i });
    const bar = search.closest("div.space-y-2");
    expect(bar).not.toBeNull();
    expect(bar as HTMLElement).toContainElement(sort);

    // Pluralised counter rendered once, in the bar's chip row — and the old
    // uppercase "RESULTS: N" band is gone.
    expect(screen.getByText("1 record")).toBeInTheDocument();
    expect(screen.queryByText(/^results:$/i)).toBeNull();
  });
});

/**
 * on the mobile list the row's ⋮ opens a real actions sheet, and
 * Delete from that sheet goes through the same ConfirmDialog as every other
 * delete on the page — never straight to the API.
 */
describe("ItemsPage — mobile actions sheet", () => {
  beforeEach(() => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation((query) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  it("opens the product dialog when a card is tapped", async () => {
    const user = userEvent.setup();
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );

    await user.click(
      await screen.findByRole("heading", { name: "Test Item", level: 3 }),
    );

    expect(await screen.findByText(/Edit product/i)).toBeInTheDocument();
    expect(await screen.findByDisplayValue("Test Item")).toBeInTheDocument();
  });

  it("opens the sheet from the row and confirms before deleting", async () => {
    const user = userEvent.setup();
    let deleteCalls = 0;
    server.use(
      http.delete("/api/v1/items/:id", () => {
        deleteCalls += 1;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );
    await screen.findAllByText(/Test Item/i);

    await user.click(screen.getByRole("button", { name: /product actions/i }));
    const sheet = await screen.findByRole("dialog", { name: /test item/i });
    // The row opens the Edit form, so the sheet is the list's way to the
    // product page.
    expect(
      within(sheet).getByRole("button", { name: /^product details$/i }),
    ).toBeInTheDocument();

    await user.click(within(sheet).getByRole("button", { name: /^delete$/i }));

    // The sheet steps aside for the page's delete dialog; the API is untouched.
    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    expect(deleteCalls).toBe(0);
  });

  it("opens the edit form from the sheet's Edit, not the row's quick actions", async () => {
    const user = userEvent.setup();
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );
    await screen.findAllByText(/Test Item/i);

    await user.click(screen.getByRole("button", { name: /product actions/i }));
    const sheet = await screen.findByRole("dialog", { name: /test item/i });
    await user.click(within(sheet).getByRole("button", { name: /^edit$/i }));

    expect(await screen.findByText(/Edit product/i)).toBeInTheDocument();
    expect(await screen.findByDisplayValue("Test Item")).toBeInTheDocument();
  });

  it("asks the row's delete why, and sends the answer", async () => {
    const user = userEvent.setup();
    let body: Record<string, unknown> | null = null;
    server.use(
      http.delete("/api/v1/items/:id", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );
    await screen.findAllByText(/Test Item/i);

    await user.click(screen.getByRole("button", { name: /product actions/i }));
    const sheet = await screen.findByRole("dialog", { name: /test item/i });
    await user.click(within(sheet).getByRole("button", { name: /^delete$/i }));

    const reason = await screen.findByTestId("deletion-reason");
    await user.selectOptions(reason, "EXPIRED");
    await user.click(screen.getByRole("button", { name: /^delete$/i }));

    await waitFor(() => expect(body).not.toBeNull());
    expect(body).toMatchObject({ reason: "EXPIRED" });
  });
});

/**
 * below 1024px the list had selectable rows at both ends and nothing
 * wired in between — the bulk bar was unreachable. Selection mode is a
 * property of the list: it is switched on from the header sheet, shows a
 * checkbox on every card, and the header's only remaining job is "Cancel".
 */
describe("ItemsPage — mobile selection mode", () => {
  beforeEach(() => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation((query) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  function renderWithHeader() {
    function Harness() {
      const [header, setHeader] = useState<PageHeaderData>({});
      return (
        <PageHeaderContext.Provider value={{ data: header, setHeader }}>
          <div data-testid="page-header">{header.actions}</div>
          <ItemsPage />
        </PageHeaderContext.Provider>
      );
    }
    return render(<Harness />);
  }

  it("toggles selection from the header sheet and exits with Cancel", async () => {
    const user = userEvent.setup();
    renderWithHeader();
    await screen.findAllByText(/Test Item/i);

    // No checkbox on the card at rest — the control costs 0px outside mode.
    expect(screen.queryByRole("checkbox")).toBeNull();

    const header = screen.getByTestId("page-header");
    await user.click(within(header).getByRole("button", { name: /more/i }));
    const sheet = await screen.findByRole("dialog", { name: /more/i });
    await user.click(
      within(sheet).getByRole("button", { name: /select products/i }),
    );

    // Every card (one here) gets a checkbox; the header trades its actions
    // for the way out.
    expect(
      screen.getByRole("checkbox", { name: /select test item/i }),
    ).toBeInTheDocument();
    expect(
      within(header).getByRole("button", { name: /^cancel$/i }),
    ).toBeInTheDocument();

    // The row tap selects — it must not open the product.
    await user.click(screen.getByRole("button", { name: /test item/i }));
    const bar = await screen.findByRole("toolbar", { name: /selected/i });
    expect(bar).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();

    // Cancel exits the mode, clears the selection, restores the card.
    await user.click(within(header).getByRole("button", { name: /^cancel$/i }));
    await waitFor(() => expect(screen.queryByRole("checkbox")).toBeNull());
    expect(screen.queryByRole("toolbar", { name: /selected/i })).toBeNull();
  });
});

/**
 * Tools for narrowing a list, over a list with nothing in it: three filter
 * chips, eight sort orders and an export button that produces an empty file.
 */
describe("ItemsPage — an account with nothing in it", () => {
  const empty = () =>
    server.use(
      http.get("/api/v1/items", () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );

  /** The export button lives in the shell header, so the test renders one. */
  function renderWithHeader() {
    function Harness() {
      const [header, setHeader] = useState<PageHeaderData>({});
      return (
        <PageHeaderContext.Provider value={{ data: header, setHeader }}>
          <div data-testid="page-header">{header.actions}</div>
          <ItemsPage />
        </PageHeaderContext.Provider>
      );
    }
    return render(<Harness />);
  }

  it("offers no way to narrow a list that is empty to begin with", async () => {
    empty();
    renderWithHeader();

    await waitFor(() => {
      expect(screen.queryByPlaceholderText(/Search products/i)).toBeNull();
    });
    expect(screen.queryByLabelText(/Sort/i)).toBeNull();
  });

  it("does not offer to export nothing", async () => {
    empty();
    renderWithHeader();

    await waitFor(() => {
      const header = screen.getByTestId("page-header");
      expect(
        within(header).getByRole("button", { name: /export/i }),
      ).toBeDisabled();
    });
  });

  it("says why Export is unavailable on an empty list", async () => {
    empty();
    renderWithHeader();

    const header = await screen.findByTestId("page-header");
    await waitFor(() => {
      expect(
        within(header).getByRole("button", { name: /export/i }),
      ).toBeDisabled();
    });
    const button = within(header).getByRole("button", { name: /export/i });
    expect(button).toHaveAccessibleDescription(
      "Nothing to export: this list is empty.",
    );
    expect(button.closest("[title]")).toHaveAttribute(
      "title",
      "Nothing to export: this list is empty.",
    );
  });

  it("keeps the controls once there is something to narrow", async () => {
    renderWithHeader();
    await screen.findAllByText(/Test Item/i);

    expect(screen.getByPlaceholderText(/Search products/i)).toBeInTheDocument();
    // The header is not part of the same render as the rows: the page hands
    // its actions to the shell from an effect, so rows on screen do not mean
    // the export button has been re-published yet. Asserting straight after
    // the rows made this test fail whenever the suite ran under enough load
    // for those two renders to separate.
    await waitFor(() => {
      const header = screen.getByTestId("page-header");
      expect(
        within(header).getByRole("button", { name: /export/i }),
      ).toBeEnabled();
    });
  });
});

describe("ItemsPage — the archive is a state of this list", () => {
  const empty = () =>
    server.use(
      http.get("/api/v1/items", () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );

  function renderPage() {
    return render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );
  }

  it("reaches the archive from the list it belongs to", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findAllByText(/Test Item/i);

    expect(screen.getByRole("tab", { name: "Active" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    await user.click(screen.getByRole("tab", { name: "Archived" }));

    expect(mockNavigate).toHaveBeenCalledWith("/inventory/items/archived");
  });

  it("keeps the tabs when there is nothing to narrow", async () => {
    // An account whose only products are archived shows an empty active list.
    // The narrowing tools go — eight ways to sort nothing — but the tabs stay,
    // or those products could only be reached by typing the URL.
    empty();
    renderPage();

    await waitFor(() => {
      expect(screen.queryByPlaceholderText(/Search products/i)).toBeNull();
    });
    expect(screen.getByRole("tab", { name: "Archived" })).toBeInTheDocument();
  });
});

describe("ItemsPage — grouping and whole-set totals", () => {
  beforeEach(() => {
    // Desktop layout, so the list renders as the grouped table.
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation((query) => ({
        matches: query === "(min-width: 1024px)",
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  it("groups rows under category headers when the toggle is on", async () => {
    server.use(
      http.get("/api/v1/items", () =>
        HttpResponse.json({
          items: [
            {
              id: "1",
              name: "Milk",
              quantity: 2,
              category_id: "1",
              location_id: "1",
              brand: "",
              created_at: "2026-01-01T00:00:00Z",
              updated_at: "2026-01-01T00:00:00Z",
            },
            {
              id: "2",
              name: "Juice",
              quantity: 1,
              category_id: "2",
              location_id: "1",
              brand: "",
              created_at: "2026-01-01T00:00:00Z",
              updated_at: "2026-01-01T00:00:00Z",
            },
          ],
          total: 2,
        }),
      ),
      http.get("/api/v1/items/aggregates", () =>
        HttpResponse.json({
          count: 2,
          total_weight: 0,
          total_value: 0,
          value_source: "purchase_price",
          unpriced_count: 0,
        }),
      ),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );

    await screen.findAllByText(/Milk/i);
    // Flat by default — no group headers until the reader asks.
    expect(screen.queryByText("1 position")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /group by category/i }));

    // One header per category on the page, each counting its own rows.
    expect(await screen.findAllByText("1 position")).toHaveLength(2);
  });

  it("footer sums come from the aggregates endpoint, not the page on screen", async () => {
    server.use(
      http.get("/api/v1/items/aggregates", () =>
        HttpResponse.json({
          count: 42,
          total_weight: 12.5,
          total_value: 0,
          value_source: "valuation_layers",
          unpriced_count: 0,
        }),
      ),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );

    // The page holds one row; the footer reports the whole set it stands for.
    await screen.findAllByText(/Test Item/i);
    expect(await screen.findByText("42 positions")).toBeInTheDocument();
    expect(screen.getByText("12.5 kg")).toBeInTheDocument();
  });

  it("the footer names the positions its value could not price", async () => {
    server.use(
      http.get("/api/v1/items/aggregates", () =>
        HttpResponse.json({
          count: 42,
          total_weight: 0,
          total_value: 65,
          value_source: "valuation_layers",
          unpriced_count: 3,
        }),
      ),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );

    await screen.findAllByText(/Test Item/i);
    // Left out of the sum, and said so — not summed as if worth nothing.
    expect(
      await screen.findByText(/3 positions have no cost history/i),
    ).toBeInTheDocument();
  });

  it("the footer says the ledger holds no value for a filtered slice", async () => {
    // The layers know products, not shelves, so a filtered view
    // gets no ledger figure — the API sends null and the footer names it
    // instead of printing stock priced at rates other shelves earned.
    server.use(
      http.get("/api/v1/items/aggregates", () =>
        HttpResponse.json({
          count: 42,
          total_weight: 0,
          total_value: null,
          value_source: "not_available_under_filter",
          unpriced_count: 0,
        }),
      ),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );

    await screen.findAllByText(/Test Item/i);
    expect(
      await screen.findByText(
        /cost layers hold no value for a filtered slice/i,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/zł/)).toBeNull();
  });
});

/**
 * The largest write surface in the application, offered to nobody who cannot
 * use it.
 *
 * Import, Add, the bulk bar and every row action end in a call the API
 * guards with `items:write`. Export is a GET and stays, because reading the
 * catalogue out is not changing it.
 */
describe("ItemsPage — an account that may not change products", () => {
  beforeEach(() => {
    signInWith(["items:read"]);
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation((query) => ({
        matches: query === "(min-width: 1024px)",
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  function renderWithHeader() {
    function Harness() {
      const [header, setHeader] = useState<PageHeaderData>({});
      return (
        <PageHeaderContext.Provider value={{ data: header, setHeader }}>
          <div data-testid="page-header">{header.actions}</div>
          <ItemsPage />
        </PageHeaderContext.Provider>
      );
    }
    return render(<Harness />);
  }

  it("says why, keeps Export, and offers neither Import nor Add", async () => {
    renderWithHeader();
    await screen.findAllByText(/Test Item/i);

    expect(
      screen.getByText(/you can view this, not change it/i),
    ).toBeInTheDocument();

    const header = screen.getByTestId("page-header");
    expect(
      within(header).getByRole("button", { name: /export/i }),
    ).toBeInTheDocument();
    expect(
      within(header).queryByRole("button", { name: /import/i }),
    ).not.toBeInTheDocument();
    expect(
      within(header).queryByRole("button", { name: /add product/i }),
    ).not.toBeInTheDocument();
  });

  it("offers no row actions to reach the write paths with", async () => {
    renderWithHeader();
    await screen.findAllByText(/Test Item/i);

    expect(
      screen.queryByRole("button", { name: /consume 1 unit/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^delete$/i }),
    ).not.toBeInTheDocument();
  });
});

/**
 * `?import=1` is a door a bookmark or the settings data card can open
 * straight onto the list. The wizard behind it writes, so the link may
 * open it only for a role the wizard would serve — a viewer following the
 * same link gets the list, not a write surface the rest of their screen
 * hides.
 */
describe("ItemsPage — the ?import=1 deep link", () => {
  beforeEach(() => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation((query) => ({
        matches: query === "(min-width: 1024px)",
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  // The deep link IS the address, and jsdom's window.location is a static
  // mock in this suite — so this block mounts its own MemoryRouter, the way
  // the storage-filter deep-link test does.
  function renderAt(
    search: string,
    entries: string[] = [`/inventory/items${search}`],
  ) {
    rtlRender(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <I18nextProvider i18n={i18n}>
          <ModulesProvider>
            <PageHeaderContext.Provider
              value={{ data: {}, setHeader: () => {} }}
            >
              <MemoryRouter
                initialEntries={entries}
                initialIndex={entries.length - 1}
              >
                <ItemsPage />
              </MemoryRouter>
            </PageHeaderContext.Provider>
          </ModulesProvider>
        </I18nextProvider>
      </QueryClientProvider>,
    );
  }

  it("opens the wizard for an account the wizard would serve", async () => {
    // The file-level beforeEach signs in with items:write.
    renderAt("?import=1");

    expect(
      await screen.findByRole("dialog", { name: /import products/i }),
    ).toBeInTheDocument();
  });

  it("closes a product dialog that a link opened by going back to the link", async () => {
    // A row of the overview links here with ?open=<id>. Closing the dialog
    // used to rewrite the address and leave the reader on the list, a screen
    // they never asked for.
    mockNavigate.mockClear();
    // Earlier tests mount a browser router, which leaves its entry count in
    // the window's history; this one runs on a memory router.
    window.history.replaceState(null, "");
    const user = userEvent.setup();
    renderAt("?open=item-1", ["/inventory", "/inventory/items?open=item-1"]);

    const dialog = await screen.findByRole("dialog");
    await user.click(
      within(dialog).getAllByRole("button", { name: /^close$/i })[0],
    );

    expect(mockNavigate).toHaveBeenCalledWith(-1);
  });

  it("hands the sheet the date a row of the overview linked to", async () => {
    const scrollIntoView = vi.spyOn(HTMLElement.prototype, "scrollIntoView");
    renderAt("?open=item-1&at=expiry");

    await screen.findByRole("dialog");
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalled());
    expect(scrollIntoView.mock.contexts[0]).toHaveAttribute(
      "data-field-key",
      "expiry_date",
    );
    scrollIntoView.mockRestore();
  });

  it("closes a product dialog that a typed address opened in place", async () => {
    mockNavigate.mockClear();
    const user = userEvent.setup();
    renderAt("?open=item-1");

    const dialog = await screen.findByRole("dialog");
    await user.click(
      within(dialog).getAllByRole("button", { name: /^close$/i })[0],
    );

    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("does not open the wizard for an account without items:write", async () => {
    signInWith(["items:read"]);
    renderAt("?import=1");

    // The page itself is up before the absence is asserted, so an open
    // wizard would have been rendered by now — the refusal is the guard's
    // doing, not an unmounted screen.
    await screen.findAllByText(/Test Item/i);
    expect(
      screen.queryByRole("dialog", { name: /import products/i }),
    ).not.toBeInTheDocument();
  });
});

describe("ItemsPage — a used-up record stays reachable", () => {
  const org = {
    id: "org-1",
    name: "Test Org",
    currency: "PLN",
    created_at: "2026-01-01T00:00:00Z",
    created_by: null,
    enabled_modules: ["core", "items"],
  };

  function captureItemRequests() {
    const seen: { url: URL; aggregates: boolean }[] = [];
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({ ...org, settings: {} }),
      ),
      // MSW matches path segments, so the aggregates route needs its own
      // handler — "*/items" never catches "/items/aggregates".
      http.get("*/items/aggregates", ({ request }) => {
        seen.push({ url: new URL(request.url), aggregates: true });
        return HttpResponse.json({
          count: 0,
          total_weight: 0,
          total_value: null,
          value_source: "unpriced",
          unpriced_count: 0,
        });
      }),
      http.get("*/items", ({ request }) => {
        seen.push({ url: new URL(request.url), aggregates: false });
        return HttpResponse.json({
          items: [{ id: "i1", name: "Test Item", quantity: 2 }],
          total: 1,
        });
      }),
    );
    return seen;
  }

  it("hands the used-up question to the API only when the chip is on", async () => {
    // Consuming the last unit files a record under the virtual Consumed
    // location, which the internal-usage default hides — the chip is the
    // way back that does not run through the storage tree.
    const seen = captureItemRequests();
    const user = userEvent.setup();
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );

    await screen.findAllByText(/Test Item/i);
    expect(seen.some(({ url }) => url.searchParams.has("include_empty"))).toBe(
      false,
    );

    await user.click(
      await screen.findByRole("button", { name: /show used up/i }),
    );

    await waitFor(() => {
      const widened = seen.filter(
        ({ url }) => url.searchParams.get("include_empty") === "true",
      );
      // The list and the footer sums widen together: one question, both
      // answered by the same flag.
      expect(widened.some(({ aggregates }) => !aggregates)).toBe(true);
      expect(widened.some(({ aggregates }) => aggregates)).toBe(true);
    });
  });
});

describe("ItemsPage — the empty list keeps the used-up way back", () => {
  const org = {
    id: "org-1",
    name: "Test Org",
    currency: "PLN",
    created_at: "2026-01-01T00:00:00Z",
    created_by: null,
    enabled_modules: ["core", "items"],
  };

  it("offers the chip even when the default view has no rows", async () => {
    // Consuming the last row of a one-product workspace empties the list,
    // and the empty state drops the narrowing tools — the chip must be the
    // exception, or the way back depends on other rows existing.
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({ ...org, settings: {} }),
      ),
      http.get("*/items", () => HttpResponse.json({ items: [], total: 0 })),
    );

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );

    expect(
      await screen.findByRole("button", { name: /show used up/i }),
    ).toBeInTheDocument();
  });
});

describe("ItemsPage — a record's location is named where the picker does not go", () => {
  const org = {
    id: "org-1",
    name: "Test Org",
    currency: "PLN",
    created_at: "2026-01-01T00:00:00Z",
    created_by: null,
    enabled_modules: ["core", "items"],
  };

  const warehouse = {
    id: "loc-warehouse",
    name: "Main Warehouse",
    full_path: "Main Warehouse",
    parent_id: null,
    is_leaf: true,
    organization_id: "org-1",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };

  // The virtual counterpart a consumed-to-zero record ends up in. No
  // picker offers it — but the row that stands in it still has to say so.
  const consumed = {
    id: "loc-consumed",
    name: "Consumed (Virtual)",
    full_path: "Consumed (Virtual)",
    parent_id: null,
    is_leaf: true,
    organization_id: "org-1",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };

  const consumedItem = {
    id: "item-consumed",
    name: "Empty Toner Cartridge",
    quantity: 0,
    location_id: consumed.id,
    organization_id: "org-1",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };

  // The naming ask and the offering ask are different requests. The naming
  // one reaches the whole tree; the offering one stays with the internal
  // slice a screen may offer.
  function useNamingHandlers() {
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({ ...org, settings: {} }),
      ),
      http.get("*/locations", ({ request }) => {
        const url = new URL(request.url);
        const naming =
          url.searchParams.get("usage") === "all" &&
          url.searchParams.get("include_archived") === "true";
        return HttpResponse.json(
          onePage(naming ? [warehouse, consumed] : [warehouse]),
        );
      }),
      http.get("*/items", () =>
        HttpResponse.json({ items: [consumedItem], total: 1 }),
      ),
      http.get("*/items/aggregates", () =>
        HttpResponse.json({ count: 1, total_weight: 0, total_value: 0 }),
      ),
    );
  }

  it("names the virtual location a consumed record stands in", async () => {
    useNamingHandlers();

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );

    await screen.findByText("Empty Toner Cartridge");
    await waitFor(() =>
      expect(screen.getAllByText("Consumed (Virtual)").length).toBeGreaterThan(
        0,
      ),
    );
    expect(screen.queryByText(/^Unknown$/i)).toBeNull();
  });

  it("shows the storage the address filtered by, though no picker offers it", async () => {
    useNamingHandlers();
    // MemoryRouter because the global test setup resets window.location
    // after each test, which breaks history.pushState in this environment
    // — the same reason StatsPage's redirect test seeds the address there.
    // The default wrapper already carries a Router, so this test assembles
    // its own providers around the MemoryRouter instead.
    rtlRender(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <I18nextProvider i18n={i18n}>
          <ModulesProvider>
            <PageHeaderContext.Provider
              value={{ data: {}, setHeader: () => {} }}
            >
              <MemoryRouter
                initialEntries={[`/inventory/items?location_id=${consumed.id}`]}
              >
                <ItemsPage />
              </MemoryRouter>
            </PageHeaderContext.Provider>
          </ModulesProvider>
        </I18nextProvider>
      </QueryClientProvider>,
    );

    await screen.findByText("Empty Toner Cartridge");
    // The filter panel's LOCATION control carries the selection's name —
    // the row already did above; the control is the second place.
    const panel = document.getElementById("items-domain-filters");
    await waitFor(() =>
      expect(
        within(panel as HTMLElement).getAllByText("Consumed (Virtual)").length,
      ).toBeGreaterThan(0),
    );
  });
});

describe("ItemsPage — a module chip whose set is empty", () => {
  beforeEach(() => {
    vi.spyOn(moduleRegistry, "getListFilterContributors").mockReturnValue([
      {
        key: "has-formula",
        label: "Has a formula",
        requiredModule: "maker",
        queryKey: ["test", "empty-template-ids"],
        fetchTemplateIds: async () => [],
      },
    ]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows no rows, says the filter found nothing, and keeps the chip to switch it off", async () => {
    // The backend reads an empty template_ids as "no filter", so an empty
    // answer sent as one would list every product under a chip that
    // promised a subset.
    const seen: URL[] = [];
    server.use(
      http.get("*/items", ({ request }) => {
        seen.push(new URL(request.url));
        return HttpResponse.json({
          items: [{ id: "i-1", name: "Test Item", quantity: 1 }],
          total: 1,
        });
      }),
    );
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );
    await screen.findAllByText(/Test Item/i);
    const before = seen.length;

    await userEvent.click(
      screen.getByRole("button", { name: /Has a formula/ }),
    );

    await waitFor(() =>
      expect(screen.queryAllByText(/Test Item/i)).toHaveLength(0),
    );
    expect(screen.getByText("Try changing filters")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Has a formula/ }),
    ).toBeInTheDocument();
    // Nothing was asked of the server that would come back unfiltered.
    expect(
      seen
        .slice(before)
        .filter(
          (u) =>
            !u.searchParams.get("template_ids") &&
            u.pathname.endsWith("/items"),
        ),
    ).toEqual([]);
  });
});

describe("ItemsPage — an empty answer under a chip", () => {
  it("says nothing matches the chip and offers to clear it, not a first product", async () => {
    // The chip narrows as much as any filter, and the account has products:
    // the answer it owes the reader is that this chip matched nothing and
    // how to widen the list back — not "add your first product".
    server.use(
      http.get("*/items", ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get("only_low_stock") === "true") {
          return HttpResponse.json({ items: [], total: 0 });
        }
        return HttpResponse.json({
          items: [{ id: "1", name: "Test Item", quantity: 10 }],
          total: 1,
        });
      }),
    );
    const user = userEvent.setup();
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <ItemsPage />
      </PageHeaderContext.Provider>,
    );
    await screen.findAllByText(/Test Item/i);

    await user.click(
      await screen.findByRole("button", { name: /running low/i }),
    );

    await waitFor(() =>
      expect(screen.queryAllByText(/Test Item/i)).toHaveLength(0),
    );
    expect(await screen.findByText("No matching products")).toBeInTheDocument();
    expect(screen.queryByText("No products")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/^Add your first product to a location\./),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /clear filters/i }));
    // The rows come back: the filter is off, and no "nothing here" answer
    // is left standing over a list that has rows again.
    await waitFor(() =>
      expect(
        screen.queryByText("No matching products"),
      ).not.toBeInTheDocument(),
    );
    expect((await screen.findAllByText(/Test Item/i)).length).toBeGreaterThan(
      0,
    );
  });
});
