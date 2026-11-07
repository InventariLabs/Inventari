import React from "react";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  useRecipes,
  useRecipe,
  useCreateRecipe,
  useDeleteRecipe,
  useAddToShoppingList,
  useOpenShoppingLists,
  useAddRecipeToCollection,
  useToggleRecipeFavorite,
} from "./useRecipes";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { queryKeys } from "@/hooks/queries/keys";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: ["recipes", "shopping_lists"],
    isModuleEnabled: (name: string) =>
      name === "recipes" || name === "shopping_lists",
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

const mockRecipe = {
  id: "1",
  name: "Pasta Bolognese",
  tags: ["Italian", "Pasta"],
  is_favorite: false,
  servings: 4,
  prep_time: 30,
  description: null,
  image_url: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{children}</BrowserRouter>
    </QueryClientProvider>
  );
};

describe("useRecipes", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns recipes list on success", async () => {
    const { result } = renderHook(() => useRecipes(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items).toHaveLength(2);
    expect(result.current.data?.total).toBe(2);
  });

  it("accepts search and filter params", async () => {
    const { result } = renderHook(
      () => useRecipes({ search: "pasta", is_favorite: true }),
      { wrapper: createWrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("returns error state on API failure", async () => {
    server.use(
      http.get("/api/v1/recipes", () =>
        HttpResponse.json({ detail: "Server error" }, { status: 500 }),
      ),
    );
    const { result } = renderHook(() => useRecipes(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useRecipe", () => {
  it("fetches single recipe by id", async () => {
    const { result } = renderHook(() => useRecipe("1"), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.id).toBe("1");
  });

  it("is disabled when id is undefined", () => {
    const { result } = renderHook(() => useRecipe(undefined), {
      wrapper: createWrapper(),
    });
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("returns error on API failure", async () => {
    server.use(
      http.get("/api/v1/recipes/:id", () =>
        HttpResponse.json({ detail: "Not Found" }, { status: 404 }),
      ),
    );
    const { result } = renderHook(() => useRecipe("999"), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useCreateRecipe", () => {
  it("creates a recipe and returns data", async () => {
    server.use(
      http.post("/api/v1/recipes", async () =>
        HttpResponse.json(
          { ...mockRecipe, id: "new-1", name: "New Recipe" },
          { status: 201 },
        ),
      ),
    );
    const { result } = renderHook(() => useCreateRecipe(), {
      wrapper: createWrapper(),
    });
    act(() => {
      result.current.mutate({ name: "New Recipe", servings: 4 } as Parameters<
        typeof result.current.mutate
      >[0]);
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.name).toBe("New Recipe");
  });
});

describe("useDeleteRecipe", () => {
  it("deletes a recipe successfully", async () => {
    server.use(
      http.delete(
        "/api/v1/recipes/:id",
        () => new HttpResponse(null, { status: 204 }),
      ),
    );
    const { result } = renderHook(() => useDeleteRecipe(), {
      wrapper: createWrapper(),
    });
    act(() => {
      result.current.mutate("1");
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});

describe("useOpenShoppingLists", () => {
  it("asks for the open lists, newest first, and answers their ids and names", async () => {
    let asked: URLSearchParams | undefined;
    server.use(
      http.get("/api/v1/shopping-lists", ({ request }) => {
        asked = new URL(request.url).searchParams;
        return HttpResponse.json({
          items: [
            { id: "active-1", name: "Week 30" },
            { id: "active-0", name: "Party" },
          ],
          total: 2,
          limit: 50,
          offset: 0,
          has_more: false,
        });
      }),
    );
    const { result } = renderHook(() => useOpenShoppingLists(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([
      { id: "active-1", name: "Week 30" },
      { id: "active-0", name: "Party" },
    ]);
    expect(asked?.get("active_only")).toBe("true");
  });

  it("answers an empty list when none is open, so the server makes one", async () => {
    server.use(
      http.get("/api/v1/shopping-lists", () =>
        HttpResponse.json({
          items: [],
          total: 0,
          limit: 1,
          offset: 0,
          has_more: false,
        }),
      ),
    );
    const { result } = renderHook(() => useOpenShoppingLists(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
  });
});

describe("useAddToShoppingList", () => {
  it("invalidates shopping list caches after adding", async () => {
    server.use(
      http.post("/api/v1/recipes/r1/add-to-shopping-list", () =>
        HttpResponse.json({ shopping_list_id: "sl1", added_count: 2 }),
      ),
    );
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>{children}</BrowserRouter>
      </QueryClientProvider>
    );

    const { result } = renderHook(() => useAddToShoppingList("r1"), {
      wrapper,
    });
    act(() => {
      result.current.mutate({ servings: 2 });
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: queryKeys.shoppingLists.all,
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: queryKeys.shoppingLists.active,
    });
  });
});

function mutationWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{children}</BrowserRouter>
    </QueryClientProvider>
  );
  return { wrapper, invalidateSpy };
}

describe("useAddRecipeToCollection", () => {
  it("invalidates the tag counts after a recipe joins a collection", async () => {
    // The chips count the collection the reader is in; a membership change
    // that leaves the cached counts alone shows an empty chip bar over a
    // collection that just got its first recipe.
    server.use(
      http.post("/api/v1/recipes/collections/c1/recipes", () =>
        HttpResponse.json(
          { collection_id: "c1", recipe_id: "r1" },
          { status: 201 },
        ),
      ),
    );
    const { wrapper, invalidateSpy } = mutationWrapper();

    const { result } = renderHook(() => useAddRecipeToCollection(), {
      wrapper,
    });
    act(() => {
      result.current.mutate({ collectionId: "c1", recipeId: "r1" });
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: queryKeys.recipes.tags,
    });
  });
});

describe("useToggleRecipeFavorite", () => {
  it("invalidates the tag counts after a favorite flips", async () => {
    // The favorites tab counts its chips within favorites.
    server.use(
      http.patch("/api/v1/recipes/r1", () =>
        HttpResponse.json({ id: "r1", is_favorite: true }),
      ),
    );
    const { wrapper, invalidateSpy } = mutationWrapper();

    const { result } = renderHook(() => useToggleRecipeFavorite(), {
      wrapper,
    });
    act(() => {
      result.current.mutate({ recipeId: "r1", newValue: true });
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: queryKeys.recipes.tags,
    });
  });
});
