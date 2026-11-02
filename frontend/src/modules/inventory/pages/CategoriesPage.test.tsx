import {
  render,
  screen,
  waitFor,
  fireEvent,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import CategoriesPage from "./CategoriesPage";
import { server } from "@/test/mocks/server";
import { withLanguage } from "@/test/mocks/i18n";
import { http, HttpResponse } from "msw";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { signInWith, signOut } from "@/test/auth";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mockCategories = [
  {
    id: "cat-1",
    name: "Dairy",
    icon: "Milk",
    group_label: "FRIDGE",
    is_active: true,
    sort_order: 1,
    field_definitions: [],
  },
  {
    id: "cat-2",
    name: "Frozen Goods",
    icon: "Snowflake",
    group_label: "FREEZER",
    is_active: true,
    sort_order: 2,
    field_definitions: [],
  },
  {
    id: "cat-3",
    name: "Pantry Items",
    icon: "Package",
    group_label: "PANTRY",
    is_active: true,
    sort_order: 3,
    field_definitions: [],
  },
];

const createQueryClient = () =>
  new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

const mockSetHeader = vi.fn();

const renderPage = (queryClient: QueryClient) =>
  render(
    <PageHeaderContext.Provider value={{ data: {}, setHeader: mockSetHeader }}>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <CategoriesPage />
        </BrowserRouter>
      </QueryClientProvider>
    </PageHeaderContext.Provider>,
  );

describe("CategoriesPage", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = createQueryClient();
    vi.clearAllMocks();
    signInWith(["categories:read", "categories:write"]);
    server.use(
      http.get("/api/v1/categories", () =>
        HttpResponse.json(onePage(mockCategories)),
      ),
    );
  });

  afterEach(() => signOut());

  it("renders category list after data loads", async () => {
    renderPage(queryClient);

    await waitFor(() => {
      expect(screen.getByText("Dairy")).toBeInTheDocument();
      expect(screen.getByText("Frozen Goods")).toBeInTheDocument();
      expect(screen.getByText("Pantry Items")).toBeInTheDocument();
    });
  });

  it("shows loading spinner initially", () => {
    renderPage(queryClient);
    // Loading spinner rendered before data arrives
    expect(
      document.querySelector("svg") || screen.queryByRole("status"),
    ).toBeTruthy();
  });

  it("filters categories by search query", async () => {
    renderPage(queryClient);

    await waitFor(() => expect(screen.getByText("Dairy")).toBeInTheDocument());

    const searchInput = screen.getByPlaceholderText(/search categories/i);
    fireEvent.change(searchInput, { target: { value: "Dairy" } });

    expect(screen.getByText("Dairy")).toBeInTheDocument();
    expect(screen.queryByText("Frozen Goods")).not.toBeInTheDocument();
    expect(screen.queryByText("Pantry Items")).not.toBeInTheDocument();
  });

  it("filters categories by group; the seeded FREEZER code keeps its translation", async () => {
    renderPage(queryClient);

    await waitFor(() => expect(screen.getByText("Dairy")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("combobox", { name: "Group" }));
    await userEvent.click(
      await screen.findByRole("option", { name: /freezer/i }),
    );

    expect(screen.getByText("Frozen Goods")).toBeInTheDocument();
    expect(screen.queryByText("Dairy")).not.toBeInTheDocument();
    expect(screen.queryByText("Pantry Items")).not.toBeInTheDocument();
  });

  it("does not group by the retired column", async () => {
    // A cached or older response may still carry `category_type`; the group
    // is read from `group_label` only, so a retired column cannot become a
    // group nobody can rename or take away again.
    server.use(
      http.get("/api/v1/categories", () =>
        HttpResponse.json(
          onePage([
            {
              ...mockCategories[0],
              group_label: null,
              category_type: "FRIDGE",
            },
          ]),
        ),
      ),
    );

    renderPage(queryClient);
    await waitFor(() => expect(screen.getByText("Dairy")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("combobox", { name: "Group" }));

    expect(screen.queryByRole("option", { name: /fridge/i })).toBeNull();
  });

  it("groups by group_label when present; an ungrouped category shows only under All groups", async () => {
    server.use(
      http.get("/api/v1/categories", () =>
        HttpResponse.json(
          onePage([
            { ...mockCategories[0], group_label: "Tools" },
            { ...mockCategories[1], group_label: null },
          ]),
        ),
      ),
    );

    renderPage(queryClient);
    await waitFor(() => expect(screen.getByText("Dairy")).toBeInTheDocument());

    // The organisation's label is offered verbatim — never translated.
    await userEvent.click(screen.getByRole("combobox", { name: "Group" }));
    await userEvent.click(await screen.findByRole("option", { name: "Tools" }));

    expect(screen.getByText("Dairy")).toBeInTheDocument();
    expect(screen.queryByText("Frozen Goods")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("combobox", { name: "Group" }));
    await userEvent.click(
      await screen.findByRole("option", { name: /all groups/i }),
    );

    expect(screen.getByText("Dairy")).toBeInTheDocument();
    expect(screen.getByText("Frozen Goods")).toBeInTheDocument();
  });

  it("uses the shared list control bar with a group dropdown, not a tab row", async () => {
    renderPage(queryClient);
    await waitFor(() => expect(screen.getByText("Dairy")).toBeInTheDocument());

    // Tabs read well at three values and fall apart at ten, and groups are
    // meant to be as many as the organisation needs — hence a Select at the
    // end of the search row (the reorder-rules location filter's layout).
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(screen.getByRole("combobox", { name: "Group" })).toBeInTheDocument();
  });

  it("shows empty state when no categories match search", async () => {
    renderPage(queryClient);

    await waitFor(() => expect(screen.getByText("Dairy")).toBeInTheDocument());

    const searchInput = screen.getByPlaceholderText(/search categories/i);
    fireEvent.change(searchInput, { target: { value: "xxxxnotexist" } });

    // All items hidden
    expect(screen.queryByText("Dairy")).not.toBeInTheDocument();
    expect(screen.queryByText("Frozen Goods")).not.toBeInTheDocument();
  });

  it("registers add button in page header", async () => {
    renderPage(queryClient);

    await waitFor(() => expect(screen.getByText("Dairy")).toBeInTheDocument());

    expect(mockSetHeader).toHaveBeenCalledWith(
      expect.objectContaining({ actions: expect.anything() }),
    );
  });

  it("shows error state when API fails", async () => {
    server.use(http.get("/api/v1/categories", () => HttpResponse.error()));

    renderPage(queryClient);

    expect(await screen.findByText("An error occurred")).toBeInTheDocument();
  });

  /**
   * A category card carried an icon and a name, and the icon was the same box
   * for every category. Nothing on it said how much the category holds, and a
   * list of 76 of them ran off the page with no way to move through it.
   */
  describe("what a card is worth", () => {
    it("says how many products the category holds", async () => {
      server.use(
        http.get("/api/v1/categories", () =>
          HttpResponse.json(
            onePage([
              { ...mockCategories[0], items_count: 12 },
              { ...mockCategories[1], items_count: 0 },
            ]),
          ),
        ),
      );

      renderPage(queryClient);

      await waitFor(() =>
        expect(screen.getByText("Dairy")).toBeInTheDocument(),
      );
      expect(screen.getByText("12")).toBeInTheDocument();
      expect(screen.getByText("0")).toBeInTheDocument();
    });

    it("pages through a long list instead of running off the screen", async () => {
      const many = Array.from({ length: 76 }, (_, i) => ({
        ...mockCategories[0],
        id: `cat-${i}`,
        name: `Category ${String(i).padStart(2, "0")}`,
        items_count: i,
      }));
      server.use(
        http.get("/api/v1/categories", () => HttpResponse.json(onePage(many))),
      );

      renderPage(queryClient);

      await waitFor(() =>
        expect(screen.getByText("Category 00")).toBeInTheDocument(),
      );
      expect(screen.queryByText("Category 60")).not.toBeInTheDocument();

      const next = screen.getByRole("button", { name: /next|następn/i });
      fireEvent.click(next);

      await waitFor(() =>
        expect(screen.queryByText("Category 00")).not.toBeInTheDocument(),
      );
    });
  });

  it("lets the count on a card lead to the products it counts", async () => {
    // The number was the only thing on the card that knew where its products
    // were, and pressing it did nothing.
    server.use(
      http.get("/api/v1/categories", () =>
        HttpResponse.json(onePage([{ ...mockCategories[0], items_count: 7 }])),
      ),
    );

    renderPage(queryClient);

    const link = await screen.findByRole("link", { name: /7/ });
    expect(link).toHaveAttribute("href", "/inventory/items?category_id=cat-1");
  });

  it("shows empty list state when no categories exist", async () => {
    server.use(
      http.get("/api/v1/categories", () => HttpResponse.json(onePage([]))),
    );

    renderPage(queryClient);

    await waitFor(() => {
      // Empty state element rendered (Tag icon area or empty message)
      expect(screen.queryByText("Dairy")).not.toBeInTheDocument();
    });
  });

  it("offers the first category as an outline under the header's filled add", async () => {
    server.use(
      http.get("/api/v1/categories", () => HttpResponse.json(onePage([]))),
    );

    renderPage(queryClient);

    const add = await screen.findByRole("button", { name: /add/i });
    expect(add).not.toHaveClass("bg-primary-600");
  });

  it("does not offer to create the first category when the request failed", async () => {
    // A dictionary of thirty-eight rendered as "add your first category" is an
    // invitation to duplicate it — every list and filter reads these names.
    server.use(
      http.get(
        "/api/v1/categories",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    renderPage(queryClient);

    expect(await screen.findByText("An error occurred")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/add your first category/i),
    ).not.toBeInTheDocument();
  });

  // A filter that found nothing used to show the "add your first category"
  // state — an invitation to create a duplicate of something that is plainly
  // there, just filtered away.
  it("gives a filtered-out list its own way back", async () => {
    renderPage(queryClient);
    await waitFor(() => expect(screen.getByText("Dairy")).toBeInTheDocument());

    const searchInput = screen.getByPlaceholderText(/search categories/i);
    fireEvent.change(searchInput, { target: { value: "nonexistent" } });

    expect(
      screen.getByText(/no categories match the filter/i),
    ).toBeInTheDocument();
    const clear = screen.getByRole("button", { name: /clear filter/i });
    fireEvent.click(clear);
    expect(screen.getByText("Dairy")).toBeInTheDocument();
    expect(screen.getByText("Frozen Goods")).toBeInTheDocument();
  });

  it("does not show the no-results state over a filter that matches", async () => {
    renderPage(queryClient);
    await waitFor(() => expect(screen.getByText("Dairy")).toBeInTheDocument());
    const searchInput = screen.getByPlaceholderText(/search categories/i);
    fireEvent.change(searchInput, { target: { value: "Dairy" } });
    expect(screen.getByText("Dairy")).toBeInTheDocument();
    expect(screen.queryByText(/no categories match the filter/i)).toBeNull();
  });

  // The backend refuses to delete a category any product points at — the
  // confirmation has to say so and name the number standing on the card
  // next to the button.
  it("tells the reader how many products block the delete", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/v1/categories", () =>
        HttpResponse.json(onePage([{ ...mockCategories[0], items_count: 5 }])),
      ),
    );

    renderPage(queryClient);
    await waitFor(() => expect(screen.getByText("Dairy")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /^delete$/i }));

    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveTextContent(/5/);
    expect(dialog).toHaveTextContent(/refused/i);
    expect(dialog).toHaveTextContent(/another category/i);
  });

  // The dialog that had just announced the refusal still offered an active red
  // "Delete" whose only possible answer was the same 400. It is an
  // informational dialog now: the button that could only fail is gone, and the
  // one left closes it.
  it("does not offer the delete it has already refused", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/v1/categories", () =>
        HttpResponse.json(onePage([{ ...mockCategories[0], items_count: 5 }])),
      ),
    );

    renderPage(queryClient);
    await waitFor(() => expect(screen.getByText("Dairy")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /^delete$/i }));

    const dialog = screen.getByRole("alertdialog");
    expect(
      within(dialog).queryByRole("button", { name: /^delete$/i }),
    ).not.toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: /^close$/i }),
    ).toBeInTheDocument();
  });

  // The other half: an empty category has nothing blocking its delete, so the
  // dialog keeps the red button that does the work.
  it("still offers the delete for a category with no products", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/v1/categories", () =>
        HttpResponse.json(onePage([{ ...mockCategories[0], items_count: 0 }])),
      ),
    );

    renderPage(queryClient);
    await waitFor(() => expect(screen.getByText("Dairy")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /^delete$/i }));

    const dialog = screen.getByRole("alertdialog");
    expect(
      within(dialog).getByRole("button", { name: /^delete$/i }),
    ).toBeInTheDocument();
  });
});

describe("CategoriesPage — module data kept out of the list", () => {
  let queryClient: QueryClient;

  // The equipment_wms onboarding seeds eight; every one carries the module's
  // context tag, so the module filter empties the list while the register
  // itself is far from empty.
  const equipmentCategories = [
    "Laptop",
    "Desktop Computer",
    "Monitor / Display",
    "Docking Station",
    "Headset",
    "Keyboard",
    "Mouse",
    "Printer",
  ].map((name, i) => ({
    id: `cat-eq-${i}`,
    name,
    icon: "Package",
    group_label: null,
    is_active: true,
    sort_order: i + 1,
    field_definitions: [],
    context_tag: "equipment",
    items_count: 0,
  }));

  beforeEach(() => {
    queryClient = createQueryClient();
    vi.clearAllMocks();
    signInWith(["categories:read", "categories:write"]);
    server.use(
      http.get("/api/v1/categories", ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get("exclude_module_contexts") === "true")
          return HttpResponse.json(onePage([]));
        return HttpResponse.json(onePage(equipmentCategories));
      }),
    );
  });

  afterEach(() => signOut());

  it("says how many the policy keeps out instead of claiming there are none", async () => {
    // The list used to read "No categories — add your first" over eight live
    // ones, and the name collision refused the reader who believed it.
    renderPage(queryClient);

    expect(
      await screen.findByText("Some categories are hidden"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/8 categories belong to a module/),
    ).toBeInTheDocument();
    expect(screen.queryByText("No categories")).toBeNull();
    expect(
      screen.getByRole("button", { name: /open settings/i }),
    ).toBeInTheDocument();
  });

  it("keeps the counter above the grid while rows are showing", async () => {
    // The counter belonged to the empty state alone: the first visible card
    // silenced it, and hidden categories behind visible ones said nothing.
    // The probe now runs beside the list for as long as the reader has not
    // narrowed it themselves.
    server.use(
      http.get("/api/v1/categories", ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get("exclude_module_contexts") === "true")
          return HttpResponse.json(onePage(mockCategories));
        return HttpResponse.json(
          onePage([...mockCategories, ...equipmentCategories]),
        );
      }),
    );

    renderPage(queryClient);

    await waitFor(() => expect(screen.getByText("Dairy")).toBeInTheDocument());
    expect(screen.getByText(/8 categories are hidden/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /open settings/i }),
    ).toBeInTheDocument();
  });

  it("steps the counter aside while the reader filters the list themselves", async () => {
    server.use(
      http.get("/api/v1/categories", ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get("exclude_module_contexts") === "true")
          return HttpResponse.json(onePage(mockCategories));
        return HttpResponse.json(
          onePage([...mockCategories, ...equipmentCategories]),
        );
      }),
    );

    renderPage(queryClient);
    await waitFor(() => expect(screen.getByText("Dairy")).toBeInTheDocument());
    expect(screen.getByText(/8 categories are hidden/)).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/search categories/i), {
      target: { value: "Dairy" },
    });

    await waitFor(() =>
      expect(screen.queryByText(/categories are hidden/)).toBeNull(),
    );
    expect(screen.getByText("Dairy")).toBeInTheDocument();
  });

  it("says the hidden-count probe failed instead of showing no counter", async () => {
    // The counter exists so that a policy-narrowed list does not read as
    // "no categories"; a probe that failed knows nothing, which is not zero.
    server.use(
      http.get("/api/v1/categories", ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get("exclude_module_contexts") === "true")
          return HttpResponse.json(onePage(mockCategories));
        return HttpResponse.json({ detail: "down" }, { status: 500 });
      }),
    );

    renderPage(queryClient);

    await waitFor(() => expect(screen.getByText("Dairy")).toBeInTheDocument());
    const alert = await screen.findByRole("alert");
    expect(
      within(alert).getByRole("button", { name: /try again/i }),
    ).toBeVisible();
  });

  it("shows no counter when the policy keeps nothing out", async () => {
    server.use(
      http.get("/api/v1/categories", () =>
        HttpResponse.json(onePage(mockCategories)),
      ),
    );

    renderPage(queryClient);

    await waitFor(() => expect(screen.getByText("Dairy")).toBeInTheDocument());
    expect(screen.queryByText(/categories are hidden/)).toBeNull();
  });

  it("the module-data switch reaches this list too", async () => {
    // The exclusion used to be a literal `true` on this page — the one list
    // where the organization's policy had no effect at either position.
    server.use(
      http.get("/api/v1/organizations/my", () =>
        HttpResponse.json({
          id: "1",
          name: "Test Organization",
          settings: { show_module_data: true },
        }),
      ),
    );

    renderPage(queryClient);

    expect(await screen.findByText("Laptop")).toBeInTheDocument();
    expect(screen.queryByText("Some categories are hidden")).toBeNull();
  });
});

// Polish counts three plural forms (1 produkt, 2–4 produkty, 5+ produktów);
// the card counter was one static key, so "2 produktów" stood under the
// number. withLanguage renders the real i18next in Polish.
describe("CategoriesPage — Polish plural counter", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = createQueryClient();
    vi.clearAllMocks();
    signInWith(["categories:read", "categories:write"]);
    server.use(
      http.get("/api/v1/categories", () =>
        HttpResponse.json(
          onePage([
            { ...mockCategories[0], items_count: 1 },
            { ...mockCategories[1], items_count: 2 },
            { ...mockCategories[2], items_count: 5 },
          ]),
        ),
      ),
    );
  });

  it("picks the few form for 2–4 and the many form for 5+", async () => {
    await withLanguage("pl", async () => {
      render(
        <PageHeaderContext.Provider
          value={{ data: {}, setHeader: mockSetHeader }}
        >
          <QueryClientProvider client={queryClient}>
            <BrowserRouter>
              <CategoriesPage />
            </BrowserRouter>
          </QueryClientProvider>
        </PageHeaderContext.Provider>,
      );

      expect(await screen.findByText("produkty")).toBeInTheDocument();
      expect(screen.getByText("produktów")).toBeInTheDocument();
      expect(screen.getByText("produkt")).toBeInTheDocument();
    });
  });
});

/**
 * A reader is told why the cards carry no actions.
 *
 * Categories are a Core register: every button on this screen ends in a call
 * the router guards with `categories:write`. Hiding them without saying so
 * leaves a grid that looks like it failed to finish loading.
 */
describe("CategoriesPage — an account that may not change a category", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = createQueryClient();
    vi.clearAllMocks();
    signInWith(["categories:read"]);
    server.use(
      http.get("/api/v1/categories", () =>
        HttpResponse.json(onePage(mockCategories)),
      ),
    );
  });

  afterEach(() => signOut());

  it("says why, and registers no add button in the header", async () => {
    renderPage(queryClient);

    expect(
      await screen.findByText(/you can view this, not change it/i),
    ).toBeInTheDocument();
    await waitFor(() => expect(mockSetHeader).toHaveBeenCalled());
    const calls = mockSetHeader.mock.calls;
    expect(calls[calls.length - 1][0].actions).toBeUndefined();
  });

  it("shows the categories, without edit or delete beside them", async () => {
    renderPage(queryClient);

    expect(await screen.findByText("Dairy")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^delete$/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^edit$/i }),
    ).not.toBeInTheDocument();
  });
});
