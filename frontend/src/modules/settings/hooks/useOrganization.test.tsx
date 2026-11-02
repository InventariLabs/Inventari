import React from "react";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  useOrganization,
  useOrganizationMembers,
  useUpdateOrganization,
} from "./useOrganization";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mockOrg = {
  id: "org1",
  name: "My Org",
  currency: "PLN",
  timezone: "Europe/Warsaw",
  created_at: new Date().toISOString(),
};

const mockMembers = [
  { id: "m1", user_id: "u1", email: "user@example.com", role: "member" },
];

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

describe("useOrganization", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/organizations/my", () => HttpResponse.json(mockOrg)),
    );
  });

  it("returns current organization", async () => {
    const { result } = renderHook(() => useOrganization(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.name).toBe("My Org");
    expect(result.current.data?.currency).toBe("PLN");
  });

  it("returns error on API failure", async () => {
    server.use(
      http.get("/api/v1/organizations/my", () =>
        HttpResponse.json({ detail: "Not Found" }, { status: 404 }),
      ),
    );
    const { result } = renderHook(() => useOrganization(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useOrganizationMembers", () => {
  beforeEach(() => {
    const paginated = {
      items: mockMembers,
      total: mockMembers.length,
      limit: 20,
      offset: 0,
      has_more: false,
    };
    server.use(
      http.get("/api/v1/organizations/my/members", () =>
        HttpResponse.json(paginated),
      ),
    );
  });

  it("returns organization members (paginated)", async () => {
    const { result } = renderHook(() => useOrganizationMembers(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items).toHaveLength(1);
    expect(result.current.data?.items[0].email).toBe("user@example.com");
    expect(result.current.data?.total).toBe(1);
  });
});

describe("useUpdateOrganization", () => {
  beforeEach(() => {
    server.use(
      http.put("/api/v1/organizations", async ({ request }) => {
        const data = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...mockOrg, ...data });
      }),
      http.get("/api/v1/organizations/my", () => HttpResponse.json(mockOrg)),
      http.get("/api/v1/organizations/my/members", () =>
        HttpResponse.json(mockMembers),
      ),
    );
  });

  it("updates organization successfully", async () => {
    const { result } = renderHook(() => useUpdateOrganization(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate({ name: "Updated Org" }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it("returns error on API failure", async () => {
    server.use(
      http.put("/api/v1/organizations", () =>
        HttpResponse.json({ detail: "Error" }, { status: 500 }),
      ),
    );
    const { result } = renderHook(() => useUpdateOrganization(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate({ name: "X" }));
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
