import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { recordRequests } from "@/test/requestLog";
import { recipesApi } from "@/modules/recipes/api/recipes";
import {
  useCreateIngredientDefault,
  useDebouncedIngredientLookup,
  useDeleteIngredientDefault,
  useImportIngredientDefaults,
  useIngredientDefaultsList,
} from "./useIngredientDefaults";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({ isLoading: false, isModuleEnabled: () => true }),
}));

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={client}>{children}</QueryClientProvider>
);

beforeEach(() => {
  client = new QueryClient();
});

describe("ingredient defaults", () => {
  it("lists with the search, language and paging it was given", async () => {
    const log = recordRequests(() => ({ items: [], total: 0 }));
    renderHook(
      () =>
        useIngredientDefaultsList({
          lang: "de",
          q: "mehl",
          limit: 20,
          offset: 40,
        }),
      { wrapper },
    );
    await waitFor(() => expect(log).toHaveLength(1));
    expect(log[0]).toMatchObject({
      method: "GET",
      path: "/recipes/ingredient-defaults",
      query: { lang: "de", q: "mehl", limit: "20", offset: "40" },
    });
  });

  it("creates and deletes a default by its own endpoint", async () => {
    const log = recordRequests(() => ({}));
    const create = renderHook(() => useCreateIngredientDefault(), { wrapper });
    const del = renderHook(() => useDeleteIngredientDefault(), { wrapper });
    await act(() =>
      create.result.current.mutateAsync({ name: "flour" } as never),
    );
    await act(() => del.result.current.mutateAsync("d1"));
    expect(log.map((r) => [r.method, r.path, r.body])).toEqual([
      ["POST", "/recipes/ingredient-defaults", { name: "flour" }],
      ["DELETE", "/recipes/ingredient-defaults/d1", undefined],
    ]);
  });

  it("uploads the file with the language as a query parameter", async () => {
    const log = recordRequests(() => ({ imported: 1 }));
    const { result } = renderHook(() => useImportIngredientDefaults(), {
      wrapper,
    });
    const file = new File(["name,kcal\nflour,364"], "defaults.csv", {
      type: "text/csv",
    });
    await act(() => result.current.mutateAsync({ file, lang: "fr" }));
    expect(log[0]).toMatchObject({
      method: "POST",
      path: "/recipes/ingredient-defaults/import",
      query: { lang: "fr" },
    });
  });

  it("refuses an oversized file before sending anything", async () => {
    const log = recordRequests(() => ({}));
    const big = new File([new Uint8Array(1)], "big.csv");
    Object.defineProperty(big, "size", { value: 500 * 1024 * 1024 });
    await expect(recipesApi.importIngredientDefaults(big)).rejects.toThrow(
      "File too large",
    );
    expect(log).toHaveLength(0);
  });

  it("exports in the chosen format and language, as a blob", async () => {
    const log = recordRequests(() => ({}));
    await recipesApi.exportIngredientDefaults("pl", "json");
    await recipesApi.exportIngredientDefaults();
    expect(log[0]).toMatchObject({
      path: "/recipes/ingredient-defaults/export",
      query: { lang: "pl", fmt: "json" },
    });
    expect(log[1].query).toEqual({ lang: "en", fmt: "csv" });
  });
});

describe("useDebouncedIngredientLookup", () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => vi.useRealTimers());

  it("waits for typing to stop, then looks up the trimmed name once", async () => {
    const log = recordRequests(() => ({ found: true }));
    const onResult = vi.fn();
    const { result } = renderHook(() => useDebouncedIngredientLookup("pl"), {
      wrapper,
    });

    result.current(" mą", onResult);
    result.current(" mąka ", onResult);
    expect(log).toHaveLength(0);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(450);
    });
    await waitFor(() => expect(onResult).toHaveBeenCalledWith({ found: true }));
    expect(log).toHaveLength(1);
    expect(log[0]).toMatchObject({
      path: "/recipes/ingredient-defaults/lookup",
      query: { name: "mąka", lang: "pl" },
    });
  });

  it("does not look up a name shorter than two characters", async () => {
    const log = recordRequests(() => ({}));
    const onResult = vi.fn();
    const { result } = renderHook(() => useDebouncedIngredientLookup(), {
      wrapper,
    });
    result.current("  a ", onResult);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    expect(log).toHaveLength(0);
    expect(onResult).not.toHaveBeenCalled();
  });

  it("stays silent when the lookup fails", async () => {
    const { server } = await import("@/test/mocks/server");
    const { http, HttpResponse } = await import("msw");
    server.use(
      http.get("/api/v1/recipes/ingredient-defaults/lookup", () =>
        HttpResponse.json({ detail: "x" }, { status: 500 }),
      ),
    );
    const onResult = vi.fn();
    const { result } = renderHook(() => useDebouncedIngredientLookup(), {
      wrapper,
    });
    result.current("flour", onResult);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    expect(onResult).not.toHaveBeenCalled();
  });
});
