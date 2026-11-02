import React, { useState, type ReactNode } from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { signInWith, signOut } from "@/test/auth";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import RecipeDetailPage from "./RecipeDetailPage";

import { toast } from "sonner";
import { formatNumberLocale } from "@/utils/formatters";

const axiosRefusal = Object.assign(
  new Error("Request failed with status code 413"),
  {
    isAxiosError: true,
    response: {
      status: 413,
      data: {
        detail: {
          code: "FILE_TOO_LARGE",
          message: "Image too large (max 5 MB)",
        },
      },
    },
  },
);

vi.mock("@/modules/recipes/hooks/useRecipes", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/modules/recipes/hooks/useRecipes")>();
  return {
    ...actual,
    // A jsdom File never survives the real multipart round-trip, so the
    // upload mutation is replaced at the boundary — what is under test is
    // the page's refusal handling, not the transport.
    useUploadRecipeImage: () => ({
      isPending: false,
      mutateAsync: vi.fn().mockRejectedValue(axiosRefusal),
    }),
    useDeleteRecipeImage: () => ({ isPending: false, mutateAsync: vi.fn() }),
  };
});

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

// The maker-bridge button renders only when the maker module is enabled.
vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: ["recipes"],
    isModuleEnabled: (name: string) => name === "recipes",
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

// The header's "Add to meal plan" action queries plans — the MSW handler for
// /recipes/meal-plans returns a paginated envelope, not the array the hook
// expects, so the page tests stub the hooks directly.
vi.mock("@/modules/recipes/hooks/useMealPlans", () => ({
  useMealPlans: () => ({ data: [] }),
  useAddMealPlanEntry: () => ({
    mutateAsync: vi.fn().mockResolvedValue({}),
    isPending: false,
  }),
}));

/** Mimics ModuleShell: renders header data set via useModulePageHeader. */
function ShellWrapper({ children }: { children: ReactNode }) {
  const [headerData, setHeaderData] = useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider
      value={{ data: headerData, setHeader: setHeaderData }}
    >
      {headerData.backTo && (
        <a data-testid="back-link" href={headerData.backTo}>
          Back
        </a>
      )}
      {headerData.title && <h1>{headerData.title}</h1>}
      {headerData.subtitle && <p>{headerData.subtitle}</p>}
      {headerData.statusBadge}
      {headerData.actions}
      {children}
    </PageHeaderContext.Provider>
  );
}

const createWrapper = (recipeId = "00000000-0000-4000-8000-000000000001") => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/recipes/${recipeId}`]}>
        <Routes>
          <Route
            path="/recipes/:id"
            element={<ShellWrapper>{children}</ShellWrapper>}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
};

describe("RecipeDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signInWith(["recipes:read", "recipes:write", "recipes:consume"]);
  });

  afterEach(() => signOut());

  it("says what the backend said when the cover is refused", async () => {
    // "Image too large (max 5 MB)" names the fix; the generic
    // "image failed" toast hid a limit the reader could respect.
    server.use(
      http.post("/api/v1/recipes/:id/image", () =>
        HttpResponse.json(
          {
            detail: {
              code: "FILE_TOO_LARGE",
              message: "Image too large (max 5 MB)",
            },
          },
          { status: 413 },
        ),
      ),
    );

    render(<RecipeDetailPage />, { wrapper: createWrapper() });
    await waitFor(() => {
      expect(screen.getByText("Pasta Carbonara")).toBeInTheDocument();
    });

    const input = document.body.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    expect(input).not.toBeNull();
    fireEvent.change(input, {
      target: { files: [new File(["x"], "cover.png", { type: "image/png" })] },
    });

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringContaining("Image too large (max 5 MB)"),
      );
    });
  });

  it("renders recipe name after loading", async () => {
    render(<RecipeDetailPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Pasta Carbonara")).toBeInTheDocument();
    });
  });

  it("renders back navigation button", async () => {
    render(<RecipeDetailPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("Pasta Carbonara")).toBeInTheDocument();
    });

    // Back link is rendered by the ShellWrapper when page sets backTo.
    // It appears one commit after the recipe data (setHeader propagates
    // through context), so it must be awaited, not asserted synchronously.
    const backLink = await screen.findByTestId("back-link");
    expect(backLink).toBeInTheDocument();
    expect(backLink).toHaveAttribute("href", "/recipes");
  });

  it("fetches nutrition once with the recipe's servings", async () => {
    let nutritionCalls = 0;
    const requestedServings: string[] = [];
    server.use(
      http.get("/api/v1/recipes/:id", () =>
        HttpResponse.json({
          id: "11111111-1111-1111-1111-111111111111",
          name: "Single Fetch",
          description: null,
          instructions: "Mix.",
          servings: 4,
          prep_time: null,
          cook_time: null,
          tags: [],
          is_favorite: false,
          ingredients: [],
          image_url: null,
          created_at: new Date().toISOString(),
        }),
      ),
      http.get("/api/v1/recipes/:id/nutrition", ({ request }) => {
        nutritionCalls++;
        requestedServings.push(
          new URL(request.url).searchParams.get("servings") ?? "",
        );
        return HttpResponse.json(null);
      }),
    );

    render(<RecipeDetailPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(nutritionCalls).toBe(1);
    });
    // The first (and only) call uses the recipe's own servings — the
    // pre-recipe "servings=1" fetch no longer happens.
    expect(requestedServings).toEqual(["4"]);
  });

  it.each([
    [0.33, false],
    [1, true],
  ])(
    "shows the hero calorie figure only when coverage %s is complete enough",
    async (coverage, shown) => {
      let served = false;
      server.use(
        http.get("/api/v1/recipes/:id", () =>
          HttpResponse.json({
            id: "11111111-1111-1111-1111-111111111111",
            name: "Tomato pasta",
            description: null,
            instructions: "Mix.",
            servings: 4,
            prep_time: null,
            cook_time: null,
            tags: [],
            is_favorite: false,
            ingredients: [],
            image_url: null,
            created_at: new Date().toISOString(),
          }),
        ),
        http.get("/api/v1/recipes/:id/nutrition", () => {
          served = true;
          return HttpResponse.json({
            coverage,
            servings: 4,
            total: {},
            per_serving: { calories_kcal: 46375 },
          });
        }),
      );

      render(<RecipeDetailPage />, { wrapper: createWrapper() });

      await screen.findByText("Tomato pasta");
      await waitFor(() => expect(served).toBe(true));
      await new Promise((r) => setTimeout(r, 50));
      await waitFor(() => {
        expect(
          screen.queryAllByText(formatNumberLocale(46375, 0)).length > 0,
        ).toBe(shown);
      });
    },
  );

  it("leaves the cost section out once the organization switched cost off", async () => {
    let costServed = false;
    server.use(
      http.get("/api/v1/recipes/:id/cost", () => {
        costServed = true;
        return HttpResponse.json({
          recipe_id: "00000000-0000-4000-8000-000000000001",
          enabled: false,
          servings: 4,
          estimated_cost: null,
          currency: null,
          cost_coverage: 0,
          mixed_currencies: false,
          missing_cost_ingredients: [],
          ingredients: [],
        });
      }),
    );

    render(<RecipeDetailPage />, { wrapper: createWrapper() });

    await waitFor(() => expect(costServed).toBe(true));
    // Present until the answer arrives, gone after it: the section is not
    // hidden by default, so its absence is the answer being read.
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: /estimated cost/i }),
      ).not.toBeInTheDocument(),
    );
  });

  it("keeps the cost section while cost calculation is on", async () => {
    server.use(
      http.get("/api/v1/recipes/:id/cost", () =>
        HttpResponse.json({
          recipe_id: "00000000-0000-4000-8000-000000000001",
          enabled: true,
          servings: 4,
          estimated_cost: null,
          currency: null,
          cost_coverage: 0,
          mixed_currencies: false,
          missing_cost_ingredients: [],
          ingredients: [],
        }),
      ),
    );

    render(<RecipeDetailPage />, { wrapper: createWrapper() });

    expect(
      await screen.findByRole("button", { name: /estimated cost/i }),
    ).toBeInTheDocument();
  });

  it("shows loading state initially", () => {
    server.use(
      http.get("/api/v1/recipes/:id", async () => {
        // Delay indefinitely
        await new Promise(() => {});
        return HttpResponse.json({});
      }),
    );

    render(<RecipeDetailPage />, { wrapper: createWrapper() });

    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows recipe description when present", async () => {
    server.use(
      http.get("/api/v1/recipes/:id", ({ params }) => {
        return HttpResponse.json({
          id: params.id,
          name: "Test Recipe With Description",
          description: "A very tasty dish",
          instructions: "Step 1. Step 2.",
          servings: 2,
          prep_time: 10,
          cook_time: 5,
          tags: ["italian"],
          is_favorite: false,
          ingredients: [],
          image_url: null,
          created_at: new Date().toISOString(),
        });
      }),
    );

    render(<RecipeDetailPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(
        screen.getByText("Test Recipe With Description"),
      ).toBeInTheDocument();
    });
    // Description is the shell header subtitle (via useModulePageHeader),
    // which lands a commit after the body — await it explicitly.
    expect(await screen.findByText("A very tasty dish")).toBeInTheDocument();
  });

  it("says why when marking a favorite is refused", async () => {
    // The toggle awaits nothing: an awaited `mutateAsync` behind it handed
    // the refusal to no one and the star simply stayed as it was.
    server.use(
      http.get("/api/v1/recipes/:id", ({ params }) =>
        HttpResponse.json({
          id: params.id,
          name: "Refused Recipe",
          description: null,
          instructions: "",
          servings: 1,
          prep_time: 5,
          cook_time: 0,
          tags: [],
          is_favorite: false,
          ingredients: [],
          image_url: null,
          created_at: new Date().toISOString(),
        }),
      ),
      http.put("/api/v1/recipes/:id", () =>
        HttpResponse.json(
          { detail: "This recipe is read-only" },
          { status: 400 },
        ),
      ),
    );

    render(<RecipeDetailPage />, { wrapper: createWrapper() });
    fireEvent.click(await screen.findByRole("button", { name: "Favorite" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("This recipe is read-only"),
    );
  });

  it("renders exactly one star, inside the favorite toggle, for a favorited recipe", async () => {
    server.use(
      http.get("/api/v1/recipes/:id", ({ params }) => {
        return HttpResponse.json({
          id: params.id,
          name: "Favorite Recipe",
          description: null,
          instructions: "",
          servings: 1,
          prep_time: 5,
          cook_time: 0,
          tags: [],
          is_favorite: true,
          ingredients: [],
          image_url: null,
          created_at: new Date().toISOString(),
        });
      }),
    );

    const { container } = render(<RecipeDetailPage />, {
      wrapper: createWrapper(),
    });

    await screen.findByText("Favorite Recipe");
    // Wait for the toggle itself, not just the title. The actions reach the
    // screen through setHeader in an effect, so they land a render after the
    // name does — counting stars on the title alone found none under load.
    const favoriteButton = await screen.findByRole("button", {
      name: "Favorite",
    });

    // The filled star on the favorite toggle is the only star on the page —
    // the old bug rendered a second one in the statusBadge next to the title.
    const stars = container.querySelectorAll<SVGElement>(".lucide-star");
    expect(stars).toHaveLength(1);
    expect(favoriteButton).toContainElement(stars[0]);

    // The title/statusBadge area carries no duplicate star. The screen title
    // and the print-only title share the recipe name, so check both.
    const titleHeadings = screen.getAllByRole("heading", {
      name: "Favorite Recipe",
    });
    expect(titleHeadings.length).toBeGreaterThan(0);
    for (const heading of titleHeadings) {
      expect(heading.querySelector(".lucide-star")).toBeNull();
    }
  });

  it.each([
    ["javascript:alert(1)", false],
    ["data:text/html,<script>alert(1)</script>", false],
    ["https://example.com/recipe", true],
  ])("renders source_url %s as a link: %s", async (sourceUrl, isLink) => {
    server.use(
      http.get("/api/v1/recipes/:id", ({ params }) =>
        HttpResponse.json({
          id: params.id,
          name: "Sourced Recipe",
          description: null,
          instructions: "Mix.",
          servings: 2,
          prep_time: null,
          cook_time: null,
          tags: [],
          is_favorite: false,
          ingredients: [],
          image_url: null,
          source_url: sourceUrl,
          created_at: new Date().toISOString(),
        }),
      ),
    );

    const { container } = render(<RecipeDetailPage />, {
      wrapper: createWrapper(),
    });
    await screen.findByText("Sourced Recipe");

    const hrefs = () =>
      Array.from(container.querySelectorAll("a")).map((a) =>
        a.getAttribute("href"),
      );

    // The title appearing does not mean the whole page has settled, and
    // the source link renders a beat later — asserting straight after
    // findByText failed roughly one run in ten. An expected link is
    // waited for; an expected *absence* is asserted as it stands, since
    // waiting could only ever hide the thing this guards against.
    if (isLink) {
      await waitFor(() => expect(hrefs()).toContain(sourceUrl));
    } else {
      expect(hrefs()).not.toContain(sourceUrl);
    }
  });

  it("keeps the print view outside the print:hidden container", async () => {
    render(<RecipeDetailPage />, { wrapper: createWrapper() });

    // "Printed on ..." is rendered only by RecipePrintView.
    const printOnlyText = await screen.findByText(/Printed on/);

    // An ancestor with `print:hidden` would make window.print() produce an
    // empty page — the print card must be its sibling, not its child.
    expect(printOnlyText.closest(".print\\:hidden")).toBeNull();
    expect(printOnlyText.closest(".print\\:block")).not.toBeNull();
  });

  it("starts cooking mode from the primary 'Cook step by step' action", async () => {
    render(<RecipeDetailPage />, { wrapper: createWrapper() });
    await screen.findByText("Pasta Carbonara");

    // Header actions arrive one commit after the recipe data (setHeader
    // propagates through context), so the button must be awaited.
    fireEvent.click(
      await screen.findByRole("button", { name: "Cook step by step" }),
    );

    // CookingMode overlay: the finish ("Done") button only exists there.
    expect(
      await screen.findByRole("button", { name: "Done" }),
    ).toBeInTheDocument();
  });

  it("moves delete, duplicate and print behind the overflow menu", async () => {
    render(<RecipeDetailPage />, { wrapper: createWrapper() });
    await screen.findByText("Pasta Carbonara");

    // Destructive and utility actions are not directly reachable.
    expect(
      screen.queryByRole("button", { name: "Delete" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Duplicate" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Print" }),
    ).not.toBeInTheDocument();

    fireEvent.click(
      await screen.findByRole("button", { name: "More actions" }),
    );

    expect(
      await screen.findByRole("button", { name: "Delete" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Duplicate" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Print" })).toBeInTheDocument();
  });

  it("moves the export actions into the overflow menu", async () => {
    render(<RecipeDetailPage />, { wrapper: createWrapper() });
    await screen.findByText("Pasta Carbonara");

    // The full-size export card is gone…
    expect(screen.queryByText("Export")).not.toBeInTheDocument();

    // …the two actions live behind the ⋯ menu.
    fireEvent.click(
      await screen.findByRole("button", { name: "More actions" }),
    );
    expect(await screen.findByText("Download JSON")).toBeInTheDocument();
    expect(screen.getByText("Copy Schema.org")).toBeInTheDocument();
  });
  it("answers a deleted recipe with a way back, not with a retry", async () => {
    // A 404 used to reach the isError branch first, so a recipe that was gone
    // came with "Try again" — a button that repeats a request the server has
    // already answered.
    server.use(
      http.get("*/api/v1/recipes/:id", () =>
        HttpResponse.json({ detail: "Not found" }, { status: 404 }),
      ),
    );
    render(<RecipeDetailPage />, { wrapper: createWrapper() });

    expect(await screen.findByText("Recipe not found")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Back to recipes" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /try again|retry/i }),
    ).not.toBeInTheDocument();
  });

  it("still offers a retry when the request itself failed", async () => {
    server.use(http.get("*/api/v1/recipes/:id", () => HttpResponse.error()));
    render(<RecipeDetailPage />, { wrapper: createWrapper() });

    expect(
      await screen.findByRole("button", { name: /try again|retry/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Recipe not found")).not.toBeInTheDocument();
  });
});

/**
 * Two permissions, two different screens.
 *
 * `recipes:write` covers changing the recipe. Finishing a picking or cooking
 * session takes stock off the shelf, and that endpoint asks for
 * `recipes:consume` instead — so a custom role holding one and not the other
 * is a real account, and offering it a session it cannot finish is the same
 * defect one screen later.
 */
describe("RecipeDetailPage — what each permission opens", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => signOut());

  it("says why, and offers no edit, for an account that may only read", async () => {
    signInWith(["recipes:read"]);
    render(<RecipeDetailPage />, { wrapper: createWrapper() });

    expect(
      await screen.findByText(/you can view this, not change it/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^edit$/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /cook step by step/i }),
    ).not.toBeInTheDocument();
  });

  it("offers editing but not cooking when the account may not consume", async () => {
    signInWith(["recipes:read", "recipes:write"]);
    render(<RecipeDetailPage />, { wrapper: createWrapper() });

    expect(
      await screen.findByRole("button", { name: /^edit$/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /cook step by step/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /get ingredients/i }),
    ).not.toBeInTheDocument();
  });
});
