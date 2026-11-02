import React from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  useNotifications,
  useMarkNotificationRead,
  useMarkAllNotificationsRead,
  useDeleteNotification,
} from "./useNotifications";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { act } from "@testing-library/react";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mockNotifications = [
  {
    id: "n1",
    title: "Low stock",
    message: "Item X is running low",
    is_read: false,
    created_at: new Date().toISOString(),
  },
];

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchInterval: false },
      mutations: { retry: false },
    },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{children}</BrowserRouter>
    </QueryClientProvider>
  );
};

describe("useNotifications", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/notifications", () =>
        HttpResponse.json(onePage(mockNotifications)),
      ),
    );
  });

  it("returns notifications on success", async () => {
    const { result } = renderHook(() => useNotifications(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].title).toBe("Low stock");
  });

  it("returns error state on API failure", async () => {
    server.use(
      http.get("/api/v1/notifications", () =>
        HttpResponse.json({ detail: "Unauthorized" }, { status: 401 }),
      ),
    );
    const { result } = renderHook(() => useNotifications(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useMarkNotificationRead", () => {
  beforeEach(() => {
    server.use(
      http.patch("/api/v1/notifications/:id", () =>
        HttpResponse.json({ id: "n1", is_read: true }),
      ),
      http.get("/api/v1/notifications", () =>
        HttpResponse.json(onePage(mockNotifications)),
      ),
    );
  });

  it("marks notification as read", async () => {
    const { result } = renderHook(() => useMarkNotificationRead(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate("n1"));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});

describe("useMarkAllNotificationsRead", () => {
  beforeEach(() => {
    server.use(
      http.post(
        "/api/v1/notifications/read-all",
        () => new HttpResponse(null, { status: 200 }),
      ),
      http.get("/api/v1/notifications", () => HttpResponse.json(onePage([]))),
    );
  });

  it("marks all notifications as read", async () => {
    const { result } = renderHook(() => useMarkAllNotificationsRead(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});

describe("useDeleteNotification", () => {
  it("deletes the notification that was dismissed and refreshes the bell, so it does not reappear", async () => {
    let listCalls = 0;
    let deleted = "";
    server.use(
      http.get("/api/v1/notifications", () => {
        listCalls += 1;
        return HttpResponse.json(onePage(mockNotifications));
      }),
      http.delete("/api/v1/notifications/:id", ({ request }) => {
        deleted = new URL(request.url).pathname;
        return HttpResponse.json({ deleted: true });
      }),
    );

    const wrapper = createWrapper();
    const list = renderHook(() => useNotifications(), { wrapper });
    await waitFor(() => expect(list.result.current.isSuccess).toBe(true));
    const callsBefore = listCalls;

    const remove = renderHook(() => useDeleteNotification(), { wrapper });
    await act(async () => {
      await remove.result.current.mutateAsync("n1");
    });

    expect(deleted).toBe("/api/v1/notifications/n1");
    await waitFor(() => expect(listCalls).toBeGreaterThan(callsBefore));
  });
});
