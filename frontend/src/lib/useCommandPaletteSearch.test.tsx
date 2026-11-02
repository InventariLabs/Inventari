import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { useCommandPaletteSearch } from "./useCommandPaletteSearch";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { withLanguage } from "@/test/mocks/i18n";
import { moduleRegistry } from "@/lib/moduleRegistry";
import type { SearchResult } from "@/lib/moduleRegistry";

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

describe("useCommandPaletteSearch", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/items", ({ request }) => {
        const url = new URL(request.url);
        const search = url.searchParams.get("search") ?? "";
        return HttpResponse.json({
          items: search
            ? [
                {
                  id: "1",
                  name: "Apple",
                  category: { id: "c1", name: "Deli", code: "deli" },
                },
              ]
            : [],
          total: search ? 1 : 0,
          limit: 5,
          offset: 0,
          has_more: false,
        });
      }),
    );
  });

  it("returns empty results for short query", () => {
    const { result } = renderHook(
      () => useCommandPaletteSearch("a", ["inventory", "recipes"]),
      { wrapper: createWrapper() },
    );
    expect(result.current.results).toEqual([]);
  });

  it("reports a failed search instead of an empty answer", async () => {
    server.use(
      http.get("/api/v1/items", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    const { result } = renderHook(
      () => useCommandPaletteSearch("apple", ["inventory"]),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.failed).toBe(true));
    expect(result.current.results).toEqual([]);
  });

  it("asks again when a failed search is repeated", async () => {
    let calls = 0;
    server.use(
      http.get("/api/v1/items", () => {
        calls += 1;
        return HttpResponse.json({ detail: "boom" }, { status: 500 });
      }),
    );
    const wrapper = createWrapper();
    const first = renderHook(
      () => useCommandPaletteSearch("apple", ["inventory"]),
      { wrapper },
    );
    await waitFor(() => expect(first.result.current.failed).toBe(true));
    first.unmount();

    const second = renderHook(
      () => useCommandPaletteSearch("apple", ["inventory"]),
      { wrapper },
    );
    await waitFor(() => expect(calls).toBe(2));
    second.unmount();
  });

  it("returns search results for valid query", async () => {
    const { result } = renderHook(
      () => useCommandPaletteSearch("apple", ["inventory", "recipes"]),
      { wrapper: createWrapper() },
    );

    await waitFor(() =>
      expect(result.current.results.length).toBeGreaterThan(0),
    );
    const itemResult = result.current.results.find(
      (r) => r.module === "inventory",
    );
    expect(itemResult).toBeDefined();
    expect(itemResult?.title).toBe("Apple");
  });

  it("subtitles a record with its category in the reader's language", async () => {
    // The hit used to read `category_name`, a field the item list does not
    // send; the category travels nested, with the code that names it.
    const { result } = renderHook(
      () => useCommandPaletteSearch("apple", ["inventory"]),
      { wrapper: createWrapper() },
    );
    await waitFor(() => expect(result.current.results).toHaveLength(1));
    expect(result.current.results[0].subtitle).toBe("Cold cuts");

    await withLanguage("pl", async () => {
      await waitFor(() =>
        expect(result.current.results[0].subtitle).toBe("Wędliny"),
      );
    });
  });

  it("returns empty when no modules enabled", async () => {
    const { result } = renderHook(() => useCommandPaletteSearch("apple", []), {
      wrapper: createWrapper(),
    });
    expect(result.current.results).toEqual([]);
  });

  it("asks the list to include used-up records", async () => {
    // A record consumed to zero sits outside the internal-usage default;
    // the palette is the one place a reader searches by name, so it must
    // ask for the emptied rows explicitly or it never finds them.
    let requestedIncludeEmpty: string | null = null;
    server.use(
      http.get("/api/v1/items", ({ request }) => {
        requestedIncludeEmpty = new URL(request.url).searchParams.get(
          "include_empty",
        );
        return HttpResponse.json({
          items: [
            {
              id: "1",
              name: "Apple",
              quantity: 0,
              category: { id: "c1", name: "Deli", code: "deli" },
            },
          ],
          total: 1,
          limit: 5,
          offset: 0,
          has_more: false,
        });
      }),
    );

    const { result } = renderHook(
      () => useCommandPaletteSearch("apple", ["inventory"]),
      { wrapper: createWrapper() },
    );
    await waitFor(() => expect(result.current.results).toHaveLength(1));
    expect(requestedIncludeEmpty).toBe("true");
  });

  it("marks a used-up hit instead of presenting it like shelf stock", async () => {
    server.use(
      http.get("/api/v1/items", ({ request }) => {
        const search = new URL(request.url).searchParams.get("search") ?? "";
        return HttpResponse.json({
          items: search
            ? [
                {
                  id: "1",
                  name: "Apple",
                  quantity: 0,
                  category: { id: "c1", name: "Deli", code: "deli" },
                },
              ]
            : [],
          total: search ? 1 : 0,
          limit: 5,
          offset: 0,
          has_more: false,
        });
      }),
    );

    const { result } = renderHook(
      () => useCommandPaletteSearch("apple", ["inventory"]),
      { wrapper: createWrapper() },
    );
    await waitFor(() => expect(result.current.results).toHaveLength(1));
    expect(result.current.results[0].subtitle).toBe("Used up");

    await withLanguage("pl", async () => {
      await waitFor(() =>
        expect(result.current.results[0].subtitle).toBe("Zużyte"),
      );
    });
  });
  describe("a product held as several records", () => {
    const tuna = (id: string, quantity: string) => ({
      id,
      name: "Tuna in Oil",
      quantity,
      template_id: "t-tuna",
      uom: { id: "u1", symbol: "pcs", name: "Pieces", category_name: "Unit" },
      category: { id: "c1", name: "Deli", code: "deli" },
    });

    it("is one hit carrying the product's whole stock", async () => {
      // Five records of one tin used to be five identical rows.
      server.use(
        http.get("/api/v1/items", () =>
          HttpResponse.json({
            items: [
              tuna("r1", "20"),
              tuna("r2", "30"),
              tuna("r3", "21"),
              { id: "o1", name: "Tuna Pasta Salad", quantity: "1" },
            ],
            total: 4,
            limit: 20,
            offset: 0,
            has_more: false,
          }),
        ),
        http.get("/api/v1/items/product-templates/t-tuna/stock", () =>
          HttpResponse.json({
            product_template_id: "t-tuna",
            total_quantity: "71.000",
            uom_symbol: "pcs",
          }),
        ),
      );

      const { result } = renderHook(
        () => useCommandPaletteSearch("tuna", ["inventory"]),
        { wrapper: createWrapper() },
      );

      await waitFor(() => expect(result.current.results).toHaveLength(2));
      const [product, other] = result.current.results;
      expect(product.title).toBe("Tuna in Oil");
      expect(product.subtitle).toBe("71 pcs. in 3 records");
      expect(product.path).toBe("/inventory/items/r1");
      expect(other.title).toBe("Tuna Pasta Salad");
    });

    it("falls back to the sum of the records found when the total cannot be read", async () => {
      server.use(
        http.get("/api/v1/items", () =>
          HttpResponse.json({
            items: [tuna("r1", "20"), tuna("r2", "30")],
            total: 2,
            limit: 20,
            offset: 0,
            has_more: false,
          }),
        ),
        http.get("/api/v1/items/product-templates/t-tuna/stock", () =>
          HttpResponse.json({ detail: "nope" }, { status: 500 }),
        ),
      );

      const { result } = renderHook(
        () => useCommandPaletteSearch("tuna", ["inventory"]),
        { wrapper: createWrapper() },
      );

      await waitFor(() => expect(result.current.results).toHaveLength(1));
      expect(result.current.results[0].subtitle).toBe("50 pcs. in 2 records");
      expect(result.current.failed).toBe(false);
    });
  });

  describe("results contributed by other modules", () => {
    afterEach(() => {
      vi.restoreAllMocks();
    });

    const recipe: SearchResult = {
      id: "r1",
      title: "Apple pie",
      path: "/recipes/r1",
      module: "recipes",
    };

    it("lists what an enabled module's provider returns beside the products", async () => {
      vi.spyOn(moduleRegistry, "getSearchProviders").mockReturnValue([
        () => Promise.resolve([recipe]),
      ]);

      const { result } = renderHook(
        () => useCommandPaletteSearch("apple", ["inventory", "recipes"]),
        { wrapper: createWrapper() },
      );

      await waitFor(() => expect(result.current.results).toHaveLength(2));
      expect(result.current.results.map((r) => r.title)).toEqual([
        "Apple",
        "Apple pie",
      ]);
      expect(result.current.failed).toBe(false);
    });

    it("keeps the other results and says so when one provider fails", async () => {
      vi.spyOn(moduleRegistry, "getSearchProviders").mockReturnValue([
        () => Promise.reject(new Error("recipes is down")),
        () => Promise.resolve([recipe]),
      ]);

      const { result } = renderHook(
        () => useCommandPaletteSearch("apple", ["inventory", "recipes"]),
        { wrapper: createWrapper() },
      );

      await waitFor(() => expect(result.current.failed).toBe(true));
      expect(result.current.results.map((r) => r.title)).toEqual([
        "Apple",
        "Apple pie",
      ]);
    });

    it("hands each provider the trimmed query", async () => {
      const provider = vi.fn(() => Promise.resolve<SearchResult[]>([]));
      vi.spyOn(moduleRegistry, "getSearchProviders").mockReturnValue([
        provider,
      ]);

      renderHook(() => useCommandPaletteSearch("  apple ", ["recipes"]), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(provider).toHaveBeenCalledWith("apple"));
    });
  });
});
