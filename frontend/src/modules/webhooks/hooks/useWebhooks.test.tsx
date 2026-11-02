import React from "react";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  useWebhooks,
  useCreateWebhook,
  useDeleteWebhook,
  useTestWebhook,
  useUpdateWebhook,
} from "./useWebhooks";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import * as modulesCtx from "@/contexts/ModulesContext";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

beforeEach(() => {
  vi.spyOn(modulesCtx, "useModules").mockReturnValue({
    enabledModules: ["webhooks"],
    isModuleEnabled: (name: string) => name === "webhooks",
    isLoading: false,
    refreshModules: vi.fn(),
    focusModule: null,
    hiddenModules: [],
  });
});

const mockWebhook = {
  id: "wh1",
  url: "https://example.com/hook",
  events: ["item.created"],
  is_active: true,
  created_at: new Date().toISOString(),
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

describe("useWebhooks", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/webhooks/endpoints", () =>
        HttpResponse.json(onePage([mockWebhook])),
      ),
    );
  });

  it("returns webhook list on success", async () => {
    const { result } = renderHook(() => useWebhooks(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].url).toBe("https://example.com/hook");
  });

  it("returns error on API failure", async () => {
    server.use(
      http.get("/api/v1/webhooks/endpoints", () =>
        HttpResponse.json({ detail: "Unauthorized" }, { status: 401 }),
      ),
    );
    const { result } = renderHook(() => useWebhooks(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useCreateWebhook", () => {
  beforeEach(() => {
    server.use(
      http.post("/api/v1/webhooks/endpoints", async ({ request }) => {
        const data = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: "wh-new", ...data }, { status: 201 });
      }),
      http.get("/api/v1/webhooks/endpoints", () =>
        HttpResponse.json(onePage([mockWebhook])),
      ),
    );
  });

  it("creates a webhook successfully", async () => {
    const { result } = renderHook(() => useCreateWebhook(), {
      wrapper: createWrapper(),
    });
    act(() =>
      result.current.mutate({
        name: "Test Hook",
        url: "https://new.example.com/hook",
        event_types: ["item.created"],
        is_active: true,
      }),
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("fails on validation error", async () => {
    server.use(
      http.post("/api/v1/webhooks/endpoints", () =>
        HttpResponse.json({ detail: "Invalid URL" }, { status: 422 }),
      ),
    );
    const { result } = renderHook(() => useCreateWebhook(), {
      wrapper: createWrapper(),
    });
    act(() =>
      result.current.mutate({
        name: "Bad Hook",
        url: "not-a-url",
        event_types: [],
        is_active: false,
      }),
    );
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useDeleteWebhook", () => {
  beforeEach(() => {
    server.use(
      http.delete(
        "/api/v1/webhooks/endpoints/:id",
        () => new HttpResponse(null, { status: 204 }),
      ),
      http.get("/api/v1/webhooks/endpoints", () =>
        HttpResponse.json(onePage([])),
      ),
    );
  });

  it("deletes a webhook successfully", async () => {
    const { result } = renderHook(() => useDeleteWebhook(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate("wh1"));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});

describe("useTestWebhook", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("refreshes the endpoint the test just changed", async () => {
    // A test *is* a delivery: it moves `last_status_code` and
    // `consecutive_failures`. The hook passed an empty invalidation, so after
    // four failing tests the card still showed "never" and a green dot.
    let listCalls = 0;
    server.use(
      http.get("/api/v1/webhooks/endpoints", () => {
        listCalls += 1;
        return HttpResponse.json(onePage([{ ...mockWebhook }]));
      }),
      http.post("/api/v1/webhooks/endpoints/:id/test", () =>
        HttpResponse.json({
          success: false,
          status_code: 405,
          error: "Method Not Allowed",
          delivery_id: "d-1",
        }),
      ),
    );

    const wrapper = createWrapper();
    const list = renderHook(() => useWebhooks(), { wrapper });
    await waitFor(() => expect(list.result.current.isSuccess).toBe(true));
    const callsBeforeTest = listCalls;

    const test = renderHook(() => useTestWebhook(), { wrapper });
    await act(async () => {
      await test.result.current.mutateAsync("wh1");
    });

    await waitFor(() => expect(listCalls).toBeGreaterThan(callsBeforeTest));
  });
});

describe("useUpdateWebhook", () => {
  it("puts the changes on the endpoint that was edited and refreshes the list, so the card shows the new name", async () => {
    let listCalls = 0;
    let put: { path: string; body: unknown } | null = null;
    server.use(
      http.get("/api/v1/webhooks/endpoints", () => {
        listCalls += 1;
        return HttpResponse.json(onePage([mockWebhook]));
      }),
      http.put("/api/v1/webhooks/endpoints/:id", async ({ request }) => {
        put = {
          path: new URL(request.url).pathname,
          body: await request.json(),
        };
        return HttpResponse.json({ ...mockWebhook, name: "Renamed" });
      }),
    );

    const wrapper = createWrapper();
    const list = renderHook(() => useWebhooks(), { wrapper });
    await waitFor(() => expect(list.result.current.isSuccess).toBe(true));
    const callsBefore = listCalls;

    const update = renderHook(() => useUpdateWebhook(), { wrapper });
    await act(async () => {
      await update.result.current.mutateAsync({
        id: "wh1",
        data: { name: "Renamed" },
      });
    });

    expect(put).toEqual({
      path: "/api/v1/webhooks/endpoints/wh1",
      body: { name: "Renamed" },
    });
    await waitFor(() => expect(listCalls).toBeGreaterThan(callsBefore));
  });
});
