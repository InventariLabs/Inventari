/**
 * "Add to shopping list" from a scan puts the product on the newest active
 * list, and makes the first list when there is none.
 */
import { describe, it, expect, vi } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import * as React from "react";

import { server } from "@/test/mocks/server";
import { useScanAddToShoppingList } from "./useScanActions";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function renderAdd() {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  return renderHook(() => useScanAddToShoppingList(), {
    wrapper: ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

function page(items: { id: string }[]) {
  return { items, total: items.length, limit: 1, offset: 0, has_more: false };
}

describe("useScanAddToShoppingList", () => {
  it("adds the product to the newest active list", async () => {
    const created = vi.fn();
    const added: { listId: string; body: unknown }[] = [];
    server.use(
      http.get("/api/v1/shopping-lists", ({ request }) => {
        const asked = new URL(request.url).searchParams;
        expect(asked.get("active_only")).toBe("true");
        return HttpResponse.json(page([{ id: "list-1" }]));
      }),
      http.post("/api/v1/shopping-lists", () => {
        created();
        return HttpResponse.json({ id: "unexpected" });
      }),
      http.post(
        "/api/v1/shopping-lists/:listId/items",
        async ({ params, request }) => {
          added.push({
            listId: String(params.listId),
            body: await request.json(),
          });
          return HttpResponse.json({ id: "item-1" });
        },
      ),
    );

    const { result } = renderAdd();
    await act(() => result.current.mutateAsync({ templateName: "Milk" }));

    expect(created).not.toHaveBeenCalled();
    expect(added).toEqual([
      { listId: "list-1", body: { name: "Milk", quantity: 1 } },
    ]);
  });

  it("makes the first list when there is no active one", async () => {
    const added: string[] = [];
    server.use(
      http.get("/api/v1/shopping-lists", () => HttpResponse.json(page([]))),
      http.post("/api/v1/shopping-lists", () =>
        HttpResponse.json({ id: "list-new" }),
      ),
      http.post("/api/v1/shopping-lists/:listId/items", ({ params }) => {
        added.push(String(params.listId));
        return HttpResponse.json({ id: "item-1" });
      }),
    );

    const { result } = renderAdd();
    act(() => result.current.mutate({ templateName: "Eggs" }));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(added).toEqual(["list-new"]);
  });
});
