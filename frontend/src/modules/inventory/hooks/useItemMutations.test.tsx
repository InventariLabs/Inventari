import React from "react";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  useCreateItem,
  useUpdateItem,
  useMoveItem,
  useDeleteItem,
  useConsumeItem,
  useDiscardItem,
  useImportItems,
} from "./useItemMutations";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

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

describe("useCreateItem", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("succeeds and returns created item", async () => {
    const { result } = renderHook(() => useCreateItem(), {
      wrapper: createWrapper(),
    });

    act(() => {
      result.current.mutate({
        unit_confirmed_over_template: false,
        name: "New Item",
        quantity: 5,
        location_id: "s1",
      });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.name).toBe("New Item");
  });

  it("returns error on API failure", async () => {
    server.use(
      http.post("/api/v1/items", () =>
        HttpResponse.json({ detail: "Validation error" }, { status: 422 }),
      ),
    );

    const { result } = renderHook(() => useCreateItem(), {
      wrapper: createWrapper(),
    });

    act(() => {
      result.current.mutate({
        unit_confirmed_over_template: false,
        name: "Bad Item",
        quantity: -1,
        location_id: "s1",
      });
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useUpdateItem", () => {
  it("succeeds and returns updated item", async () => {
    const { result } = renderHook(() => useUpdateItem(), {
      wrapper: createWrapper(),
    });

    act(() => {
      result.current.mutate({ id: "1", data: { name: "Updated Name" } });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.id).toBe("1");
  });

  it("refreshes the product list of every location", async () => {
    // A product edit can move the product, so "which shelf changed" has two
    // answers and the mutation knows neither. Invalidating only the flat
    // items list left the location screen showing the state from before the
    // save for the full five-minute staleTime — which is what a save that
    // did not work looks like.
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const invalidated: unknown[] = [];
    const spy = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockImplementation((filters) => {
        invalidated.push(filters?.queryKey);
        return Promise.resolve();
      });

    const { result } = renderHook(() => useUpdateItem(), {
      wrapper: ({ children }: { children: React.ReactNode }) => (
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>{children}</BrowserRouter>
        </QueryClientProvider>
      ),
    });

    act(() => {
      result.current.mutate({ id: "1", data: { name: "Updated Name" } });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidated).toContainEqual(["storage-items"]);
    spy.mockRestore();
  });

  it("fails on 404", async () => {
    server.use(
      http.put("/api/v1/items/:id", () =>
        HttpResponse.json({ detail: "Not Found" }, { status: 404 }),
      ),
    );

    const { result } = renderHook(() => useUpdateItem(), {
      wrapper: createWrapper(),
    });

    act(() => result.current.mutate({ id: "999", data: { name: "X" } }));

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useMoveItem", () => {
  it("invalidates the detail query the position screen reads", async () => {
    // The position screen reads the detail key under the ["items"] root,
    // not the lists. A move that
    // only invalidated lists left a consumed-to-zero position reporting
    // "Consumed (Virtual)" with the old instruction paragraph after the
    // success toast, until a manual reload.
    server.use(
      http.patch("/api/v1/items/1/move", () =>
        HttpResponse.json({ id: "1", location_id: "s2" }),
      ),
    );
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const invalidated: unknown[] = [];
    const spy = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockImplementation((filters) => {
        invalidated.push(filters?.queryKey);
        return Promise.resolve();
      });

    const { result } = renderHook(() => useMoveItem(), {
      wrapper: ({ children }: { children: React.ReactNode }) => (
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>{children}</BrowserRouter>
        </QueryClientProvider>
      ),
    });

    act(() => {
      result.current.mutate({ itemId: "1", storageLocationId: "s2" });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidated).toContainEqual(["items", "detail", "1"]);
    spy.mockRestore();
  });
});

describe("useDeleteItem", () => {
  it("succeeds on delete", async () => {
    const { result } = renderHook(() => useDeleteItem(), {
      wrapper: createWrapper(),
    });

    act(() => result.current.mutate({ itemId: "1" }));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("returns error when item not found", async () => {
    server.use(
      http.delete("/api/v1/items/:id", () =>
        HttpResponse.json({ detail: "Not Found" }, { status: 404 }),
      ),
    );

    const { result } = renderHook(() => useDeleteItem(), {
      wrapper: createWrapper(),
    });

    act(() => result.current.mutate({ itemId: "999" }));

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useConsumeItem", () => {
  beforeEach(() => {
    server.use(
      http.patch("/api/v1/items/:id/consume", () =>
        HttpResponse.json({ id: "1", quantity: 9 }),
      ),
    );
  });

  it("succeeds with default quantity", async () => {
    const { result } = renderHook(() => useConsumeItem(), {
      wrapper: createWrapper(),
    });

    act(() => result.current.mutate({ itemId: "1" }));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("returns error on API failure", async () => {
    server.use(
      http.patch("/api/v1/items/:id/consume", () =>
        HttpResponse.json({ detail: "Server Error" }, { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useConsumeItem(), {
      wrapper: createWrapper(),
    });

    act(() => result.current.mutate({ itemId: "1", quantity: 99 }));

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

function importResponse(created: {
  locations?: string[];
  categories?: string[];
}) {
  return {
    total: 1,
    imported: 1,
    joined_existing: 0,
    updated: 0,
    skipped: 0,
    failed: 0,
    errors: [],
    created_locations: created.locations ?? [],
    created_categories: created.categories ?? [],
  };
}

function spyOnInvalidations() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const invalidated: unknown[] = [];
  const spy = vi
    .spyOn(queryClient, "invalidateQueries")
    .mockImplementation((filters) => {
      invalidated.push(filters?.queryKey);
      return Promise.resolve();
    });
  return { queryClient, invalidated, spy };
}

function importWrapper(queryClient: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{children}</BrowserRouter>
    </QueryClientProvider>
  );
}

describe("useImportItems", () => {
  /**
   * The summary said "1 LOCATION CREATED Szafak" while the list beside it
   * read "Herbata · Unknown": the import refreshed the products but not the
   * storages the row's location column resolves its name from, and only a
   * reload refetched that list.
   */
  it("refreshes storages the import founded locations in", async () => {
    server.use(
      http.post("/api/v1/items/import", () =>
        HttpResponse.json(importResponse({ locations: ["Szafak"] })),
      ),
    );
    const { queryClient, invalidated, spy } = spyOnInvalidations();

    const { result } = renderHook(() => useImportItems(), {
      wrapper: importWrapper(queryClient),
    });

    act(() => {
      result.current.mutate({
        file: new File(["name,location\nHerbata,Szafak"], "items.csv"),
        mapping: {},
      });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidated).toContainEqual(["storages"]);
    spy.mockRestore();
  });

  /**
   * A long sheet is answered with a job and read until it ends. The screen
   * waits on the same mutation either way, so the refresh that follows an
   * import must follow this one too.
   */
  it("follows an import the server moved to the background", async () => {
    let reads = 0;
    server.use(
      http.post("/api/v1/items/import", () =>
        HttpResponse.json(
          { id: "job-1", status: "running", total: 1, processed: 0 },
          { status: 202 },
        ),
      ),
      http.get("/api/v1/items/import/jobs/job-1", () => {
        reads += 1;
        return HttpResponse.json(
          reads < 2
            ? { id: "job-1", status: "running", total: 1, processed: 0 }
            : {
                id: "job-1",
                status: "done",
                total: 1,
                processed: 1,
                result: importResponse({ locations: ["Szafak"] }),
              },
        );
      }),
    );
    const { queryClient, invalidated, spy } = spyOnInvalidations();

    const { result } = renderHook(() => useImportItems(), {
      wrapper: importWrapper(queryClient),
    });

    act(() => {
      result.current.mutate({
        file: new File(["name,location\nHerbata,Szafak"], "items.csv"),
        mapping: {},
      });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true), {
      timeout: 6000,
    });
    expect(result.current.data?.imported).toBe(1);
    expect(invalidated).toContainEqual(["storages"]);
    spy.mockRestore();
  });

  it("reports an import the background could not finish", async () => {
    server.use(
      http.post("/api/v1/items/import", () =>
        HttpResponse.json(
          { id: "job-2", status: "running", total: 1, processed: 0 },
          { status: 202 },
        ),
      ),
      http.get("/api/v1/items/import/jobs/job-2", () =>
        HttpResponse.json({
          id: "job-2",
          status: "failed",
          total: 1,
          processed: 0,
          error: "The import was interrupted before it finished.",
        }),
      ),
    );
    const { queryClient, spy } = spyOnInvalidations();

    const { result } = renderHook(() => useImportItems(), {
      wrapper: importWrapper(queryClient),
    });

    act(() => {
      result.current.mutate({
        file: new File(["name\nHerbata"], "items.csv"),
        mapping: {},
      });
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toContain("interrupted");
    spy.mockRestore();
  });

  it("refreshes categories the import founded", async () => {
    server.use(
      http.post("/api/v1/items/import", () =>
        HttpResponse.json(importResponse({ categories: ["Napoje"] })),
      ),
    );
    const { queryClient, invalidated, spy } = spyOnInvalidations();

    const { result } = renderHook(() => useImportItems(), {
      wrapper: importWrapper(queryClient),
    });

    act(() => {
      result.current.mutate({
        file: new File(["name,category\nHerbata,Napoje"], "items.csv"),
        mapping: {},
      });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidated).toContainEqual(["categories"]);
    spy.mockRestore();
  });

  it("leaves org data alone when the import founded none", async () => {
    server.use(
      http.post("/api/v1/items/import", () =>
        HttpResponse.json(importResponse({})),
      ),
    );
    const { queryClient, invalidated, spy } = spyOnInvalidations();

    const { result } = renderHook(() => useImportItems(), {
      wrapper: importWrapper(queryClient),
    });

    act(() => {
      result.current.mutate({
        file: new File(["name\nHerbata"], "items.csv"),
        mapping: {},
      });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidated).not.toContainEqual(["storages"]);
    expect(invalidated).not.toContainEqual(["categories"]);
    spy.mockRestore();
  });
});

describe("useDiscardItem", () => {
  beforeEach(() => {
    server.use(
      http.patch("/api/v1/items/:id/discard", () =>
        HttpResponse.json({ id: "1", quantity: 0 }),
      ),
    );
  });

  it("succeeds", async () => {
    const { result } = renderHook(() => useDiscardItem(), {
      wrapper: createWrapper(),
    });

    act(() => result.current.mutate({ itemId: "1", quantity: 1 }));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("sends the reason as the reader picked it", async () => {
    // The reason is what the ledger, the journal and the waste report read;
    // this hook was unreachable from the app for months, so every disposal
    // was filed as USED and the waste report read 0.00 over a full bin.
    let sentBody: Record<string, unknown> | undefined;
    server.use(
      http.patch("/api/v1/items/:id/discard", async ({ request }) => {
        sentBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: "1", quantity: 0 });
      }),
    );
    const { result } = renderHook(() => useDiscardItem(), {
      wrapper: createWrapper(),
    });

    act(() =>
      result.current.mutate({ itemId: "1", quantity: 4, reason: "DISPOSED" }),
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(sentBody).toMatchObject({ quantity: 4, reason: "DISPOSED" });
  });
});
