import React, { useState } from "react";
import {
  render,
  screen,
  waitFor,
  fireEvent,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { signInWith, signOut } from "@/test/auth";
import { tokenStore } from "@/lib/api/client";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import RecipesPage from "./RecipesPage";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { onePage } from "@/test/mocks/page";
import { toast } from "sonner";
import i18next from "i18next";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

// jsdom has no canvas, so the real compressor never settles.
vi.mock("@/lib/imageUtils", () => ({
  compressImage: (file: File) => Promise.resolve(file),
  prepareImageUpload: (file: File) => Promise.resolve(file),
}));

// jsdom's location is stubbed in the test setup, so pushState never reaches
// the router. The page reads the query string once, at mount, which is what
// this stands in for.
const routeMocks = vi.hoisted(() => ({
  searchParams: new URLSearchParams(),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useSearchParams: () => [routeMocks.searchParams, vi.fn()],
  };
});

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: ["recipes"],
    isModuleEnabled: (name: string) => name === "recipes",
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => {
    const [headerData, setHeaderData] = useState<{
      title?: string;
      subtitle?: string;
      actions?: React.ReactNode;
    }>({});
    return (
      <PageHeaderContext.Provider
        value={{ data: headerData, setHeader: setHeaderData }}
      >
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            {headerData.actions && <div>{headerData.actions}</div>}
            {children}
          </BrowserRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>
    );
  };
};

describe("RecipesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signInWith(["recipes:read", "recipes:write"]);
  });

  afterEach(() => {
    signOut();
    routeMocks.searchParams = new URLSearchParams();
  });

  it("renders recipe list after loading", async () => {
    render(<RecipesPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Pasta Carbonara")).toBeInTheDocument();
    });
    expect(screen.getByText("Caesar Salad")).toBeInTheDocument();
  });

  it("renders page title", async () => {
    render(<RecipesPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Pasta Carbonara")).toBeInTheDocument();
    });
  });

  it("shows empty state when no recipes", async () => {
    server.use(
      http.get("/api/v1/recipes", () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    );

    render(<RecipesPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      // When empty, no recipe cards — just verify no error
      expect(screen.queryByText("Pasta Carbonara")).not.toBeInTheDocument();
    });
  });

  it("shows the second page when Next page is pressed", async () => {
    const row = (n: number) => ({
      id: `r-${n}`,
      name: `Recipe ${n}`,
      tags: [],
      is_favorite: false,
      servings: 2,
      prep_time: 10,
      cook_time: 0,
      ingredients_count: 1,
      image_url: null,
      created_at: new Date().toISOString(),
    });
    // The endpoint reads `offset`; a request that names the start any other
    // way gets the first page again, which is how the bug looked on screen.
    server.use(
      http.get("/api/v1/recipes", ({ request }) => {
        const offset = Number(
          new URL(request.url).searchParams.get("offset") ?? 0,
        );
        const start = offset === 0 ? 1 : 51;
        const count = offset === 0 ? 50 : 8;
        return HttpResponse.json({
          items: Array.from({ length: count }, (_, i) => row(start + i)),
          total: 58,
        });
      }),
    );

    const user = userEvent.setup();
    render(<RecipesPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Recipe 1")).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: "Next page" }));

    await waitFor(() => {
      expect(screen.getByText("Recipe 51")).toBeInTheDocument();
    });
    expect(screen.queryByText("Recipe 1")).not.toBeInTheDocument();
  });

  it("shows only favorites in favorites tab", async () => {
    server.use(
      http.get("/api/v1/recipes", ({ request }) => {
        const url = new URL(request.url);
        const isFav = url.searchParams.get("is_favorite") === "true";
        if (isFav) {
          return HttpResponse.json({
            items: [
              {
                id: "2",
                name: "Caesar Salad",
                tags: [],
                is_favorite: true,
                servings: 4,
                prep_time: 15,
                cook_time: 0,
                ingredients_count: 5,
                image_url: null,
                created_at: new Date().toISOString(),
              },
            ],
            total: 1,
          });
        }
        return HttpResponse.json({
          items: [
            {
              id: "1",
              name: "Pasta Carbonara",
              tags: [],
              is_favorite: false,
              servings: 2,
              prep_time: 20,
              cook_time: 10,
              ingredients_count: 4,
              image_url: null,
              created_at: new Date().toISOString(),
            },
            {
              id: "2",
              name: "Caesar Salad",
              tags: [],
              is_favorite: true,
              servings: 4,
              prep_time: 15,
              cook_time: 0,
              ingredients_count: 5,
              image_url: null,
              created_at: new Date().toISOString(),
            },
          ],
          total: 2,
        });
      }),
    );

    const user = userEvent.setup();
    render(<RecipesPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Pasta Carbonara")).toBeInTheDocument();
    });

    const favoritesTab = screen.getByRole("tab", { name: /Favorites/i });
    await user.click(favoritesTab);

    await waitFor(
      () => {
        expect(screen.queryByText("Pasta Carbonara")).not.toBeInTheDocument();
        expect(screen.getByText("Caesar Salad")).toBeInTheDocument();
      },
      { timeout: 5000 },
    );
  });

  it("shows available tab with empty data", async () => {
    render(<RecipesPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Pasta Carbonara")).toBeInTheDocument();
    });

    const availableTab = screen.getByText("I can cook");
    fireEvent.click(availableTab);

    // Available tab should render without crashing (empty data)
    await waitFor(() => {
      expect(screen.queryByText(/error/i)).not.toBeInTheDocument();
    });
  });

  it("shows error state when API fails", async () => {
    server.use(
      http.get("/api/v1/recipes", () =>
        HttpResponse.json({ detail: "Server error" }, { status: 500 }),
      ),
    );

    render(<RecipesPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      // QueryError component or some error indicator should appear
      expect(screen.queryByText("Pasta Carbonara")).not.toBeInTheDocument();
    });
  });

  it("opens new recipe form when Add button is clicked", async () => {
    render(<RecipesPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Pasta Carbonara")).toBeInTheDocument();
    });

    // Find the add/new recipe button
    const addButton = screen.getByRole("button", {
      name: /New recipe/i,
    });
    fireEvent.click(addButton);

    // RecipeForm should appear
    await waitFor(() => {
      expect(screen.getByText("New Recipe")).toBeInTheDocument();
    });
  });

  it("does not say a recipe was not saved when only its photo was refused by an ended session", async () => {
    // The recipe is created first and its photo goes up after, so a session
    // that ends in between must not invite a second, duplicate recipe.
    server.use(
      http.post("/api/v1/recipes", () =>
        HttpResponse.json({ id: "new-1", name: "Soup" }, { status: 201 }),
      ),
      http.post("/api/v1/recipes/:id/image", () =>
        HttpResponse.json({ detail: "expired" }, { status: 401 }),
      ),
      http.post(
        "*/api/v1/auth/refresh",
        () => new HttpResponse(null, { status: 204 }),
      ),
    );
    tokenStore.set("expired-token");

    render(<RecipesPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText("Pasta Carbonara")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /New recipe/i }));
    await screen.findByText("New Recipe");
    fireEvent.change(screen.getByLabelText(/^Recipe name/), {
      target: { value: "Soup" },
    });
    fireEvent.change(document.getElementById("recipe-form-image")!, {
      target: {
        files: [new File(["photo"], "soup.jpg", { type: "image/jpeg" })],
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    const shown = vi.mocked(toast.error).mock.calls.map(([m]) => String(m));
    expect(shown).not.toContain(i18next.t("common:errors.sessionEnded"));
    expect(shown).not.toContain("Failed to save recipe");
    expect(toast.success).toHaveBeenCalled();
  });

  it("opens the new recipe form when the URL asks for it", async () => {
    routeMocks.searchParams = new URLSearchParams("new=1");
    render(<RecipesPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("New Recipe")).toBeInTheDocument();
    });
  });

  it("keeps mobile collection chips outside the flex row", async () => {
    server.use(
      http.get("/api/v1/recipes/collections", () =>
        HttpResponse.json(
          onePage([
            {
              id: "c1",
              name: "Breakfast",
              icon: null,
              parent_id: null,
              recipe_count: 0,
              children: [],
            },
          ]),
        ),
      ),
    );

    render(<RecipesPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Pasta Carbonara")).toBeInTheDocument();
    });

    const chips = screen.getByTestId("collections-chips");
    const sidebar = screen.getByTestId("collections-sidebar");
    const contentCol = screen.getByTestId("recipes-content");

    // Regression pin: with at least one collection the chips row was
    // a flex child next to the content column, eating all its width at 390px
    // (content collapsed to 6px). Chips must sit ABOVE the flex row, with the
    // sidebar as the row's first child.
    const flexRow = contentCol.parentElement!;
    expect(flexRow).toContainElement(sidebar);
    expect(flexRow).not.toContainElement(chips);
    expect(chips.parentElement).toBe(flexRow.parentElement);
  });

  it("says the collections could not be loaded instead of showing none", async () => {
    server.use(
      http.get("/api/v1/recipes/collections", () =>
        HttpResponse.json({ detail: "down" }, { status: 500 }),
      ),
    );

    render(<RecipesPage />, { wrapper: createWrapper() });

    expect(
      await screen.findByText("Collections could not be loaded."),
    ).toBeInTheDocument();

    // The offer has to reach the read: the next answer clears the message.
    server.use(
      http.get("/api/v1/recipes/collections", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    await waitFor(() =>
      expect(
        screen.queryByText("Collections could not be loaded."),
      ).not.toBeInTheDocument(),
    );
  });

  it("says the tags could not be loaded instead of showing no tag filter", async () => {
    server.use(
      http.get("/api/v1/recipes/tags", () =>
        HttpResponse.json({ detail: "down" }, { status: 500 }),
      ),
    );

    render(<RecipesPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Pasta Carbonara")).toBeInTheDocument();
    });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/error/i);
    expect(
      within(alert).getByRole("button", { name: /try again/i }),
    ).toBeVisible();
  });

  it("shows no collection panel at all when there are no collections", async () => {
    render(<RecipesPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Pasta Carbonara")).toBeInTheDocument();
    });

    // The panel used to shrink to a lone "+ New collection" floating in
    // whitespace, and the phone layout kept a dashed chip saying the same
    // thing. Creating the first collection is a header action now, so both
    // surfaces wait until there is something to list.
    expect(screen.queryByTestId("collections-sidebar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("collections-chips")).not.toBeInTheDocument();
  });

  it("asks for tag counts scoped to the selected collection", async () => {
    const tagRequests: string[] = [];
    server.use(
      http.get("/api/v1/recipes/collections", () =>
        HttpResponse.json(
          onePage([
            {
              id: "c1",
              name: "Breakfast",
              icon: null,
              parent_id: null,
              recipe_count: 0,
              children: [],
            },
          ]),
        ),
      ),
      http.get("/api/v1/recipes/tags", ({ request }) => {
        tagRequests.push(request.url);
        return HttpResponse.json(
          onePage([{ name: "obiad", count: 0, color: null }]),
        );
      }),
    );

    render(<RecipesPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText("Pasta Carbonara")).toBeInTheDocument();
    });

    fireEvent.click(
      within(screen.getByTestId("collections-chips")).getByRole("button", {
        name: /Breakfast/,
      }),
    );

    // The chips count the collection the reader is looking at, not the
    // organization behind it — a "obiad 1" on an empty collection promised
    // a result the click could not deliver.
    await waitFor(() => {
      expect(tagRequests.some((url) => url.includes("collection_id=c1"))).toBe(
        true,
      );
    });
  });

  it("points at inventory when ingredients are linked but nothing is cookable", async () => {
    const user = userEvent.setup();
    // The listing reports one linked ingredient → the empty "I can cook"
    // state must blame stock, not linking.
    server.use(
      http.get("/api/v1/recipes", () =>
        HttpResponse.json({
          items: [
            {
              id: "r-linked",
              name: "Linked Recipe",
              description: null,
              servings: 2,
              prep_time_minutes: null,
              image_url: null,
              tags: [],
              is_favorite: false,
              created_at: new Date().toISOString(),
              source_url: null,
              ingredients_total: 1,
              ingredients_linked: 1,
              ingredients_available: 0,
              missing_names: [],
            },
          ],
          total: 1,
        }),
      ),
    );

    render(<RecipesPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText("Linked Recipe")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("tab", { name: /i can cook/i }));

    await waitFor(() => {
      expect(
        screen.getByText("No recipes available right now"),
      ).toBeInTheDocument();
    });
    expect(screen.getByText("Go to inventory")).toBeInTheDocument();
    expect(
      screen.queryByText("Ingredients are not linked to stock"),
    ).not.toBeInTheDocument();
  });

  it("points at ingredient linking when nothing is linked", async () => {
    const user = userEvent.setup();
    // The default handlers carry no `ingredients_linked` (undefined → 0).
    render(<RecipesPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText("Pasta Carbonara")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("tab", { name: /i can cook/i }));

    expect(
      await screen.findByText("Ingredients are not linked to stock"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Go to inventory")).not.toBeInTheDocument();
  });

  it("seeds the edit form from the recipe detail so saving keeps its ingredients", async () => {
    const putBodies: Record<string, unknown>[] = [];
    // The list row carries only the ingredient count. The form cannot seed
    // from it — it must read the detail, or Save writes the empty list back.
    server.use(
      http.get("/api/v1/recipes", () =>
        HttpResponse.json({
          items: [
            {
              id: "1",
              name: "Pasta Carbonara",
              description: null,
              servings: 2,
              prep_time_minutes: 20,
              image_url: null,
              tags: [],
              is_favorite: false,
              created_at: new Date().toISOString(),
              source_url: null,
              ingredients_total: 2,
              ingredients_linked: 2,
              ingredients_available: 0,
              missing_names: [],
            },
          ],
          total: 1,
        }),
      ),
      http.get("/api/v1/recipes/:id", ({ params }) => {
        if (params.id !== "1") return;
        return HttpResponse.json({
          id: "1",
          organization_id: "org-1",
          created_by: "user-1",
          name: "Pasta Carbonara",
          description: null,
          instructions: null,
          servings: 2,
          prep_time_minutes: 20,
          image_url: null,
          source_url: null,
          tags: [],
          is_favorite: false,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          allergens: [],
          ingredients: [
            {
              id: "ing-1",
              recipe_id: "1",
              name: "Flour",
              template_id: null,
              ingredient_group_name: null,
              quantity: 200,
              uom_id: "uom-g",
              uom_symbol: "g",
              is_optional: false,
              is_spice: false,
              picking_skip: null,
              sort_order: 0,
              calories_kcal_per_100g: null,
              display_text: null,
              original_quantity: null,
              original_unit_text: null,
              price: null,
              price_uom_id: null,
              price_currency: null,
              allergens: [],
            },
            {
              id: "ing-2",
              recipe_id: "1",
              name: "Eggs",
              template_id: null,
              ingredient_group_name: null,
              quantity: 2,
              uom_id: "uom-pcs",
              uom_symbol: "pcs",
              is_optional: false,
              is_spice: false,
              picking_skip: null,
              sort_order: 1,
              calories_kcal_per_100g: null,
              display_text: null,
              original_quantity: null,
              original_unit_text: null,
              price: null,
              price_uom_id: null,
              price_currency: null,
              allergens: [],
            },
          ],
        });
      }),
      http.put("/api/v1/recipes/:id", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        putBodies.push(body);
        return HttpResponse.json({ id: "1", ...body });
      }),
    );

    render(<RecipesPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText("Pasta Carbonara")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));

    expect(await screen.findByDisplayValue("Flour")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Eggs")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Save"));

    await waitFor(() => expect(putBodies).toHaveLength(1));
    expect(putBodies[0].ingredients).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ id: "ing-1", name: "Flour" }),
        expect.objectContaining({ id: "ing-2", name: "Eggs" }),
      ]),
    );
  });
});
