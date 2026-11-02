import React from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  useAdminAnnouncements,
  useActiveAnnouncements,
} from "./useAnnouncements";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mockAnnouncement = {
  id: "a1",
  title: "Maintenance",
  content: "Scheduled downtime Saturday",
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

describe("useAdminAnnouncements", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/announcements", () =>
        HttpResponse.json(onePage([mockAnnouncement])),
      ),
    );
  });

  it("returns all announcements for admins", async () => {
    const { result } = renderHook(() => useAdminAnnouncements(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].title).toBe("Maintenance");
  });

  it("returns error on API failure", async () => {
    server.use(
      http.get("/api/v1/announcements", () =>
        HttpResponse.json({ detail: "Forbidden" }, { status: 403 }),
      ),
    );
    const { result } = renderHook(() => useAdminAnnouncements(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useActiveAnnouncements", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/announcements/active", () =>
        HttpResponse.json(onePage([mockAnnouncement])),
      ),
    );
  });

  it("returns only active announcements", async () => {
    const { result } = renderHook(() => useActiveAnnouncements(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].is_active).toBe(true);
  });
});
