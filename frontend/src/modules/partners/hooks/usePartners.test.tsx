import React from "react";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  usePartners,
  useCreatePartner,
  useUpdatePartner,
  useDeactivatePartner,
  useActivatePartner,
} from "../hooks/usePartners";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import * as modulesCtx from "@/contexts/ModulesContext";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

beforeEach(() => {
  vi.spyOn(modulesCtx, "useModules").mockReturnValue({
    enabledModules: ["partners"],
    isModuleEnabled: (name: string) => name === "partners",
    isLoading: false,
    refreshModules: vi.fn(),
    focusModule: null,
    hiddenModules: [],
  });
});

const mockPartner = {
  id: "p1",
  organization_id: "org-1",
  name: "Acme Corp",
  code: null,
  type: "SUPPLIER" as const,
  tax_id: null,
  email: "info@acme.com",
  phone: null,
  website: null,
  contact_person: null,
  address: null,
  notes: null,
  is_active: true,
  created_by: null,
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

describe("usePartners", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/partners", () =>
        HttpResponse.json({ items: [mockPartner], total: 1 }),
      ),
    );
  });

  it("returns partner list on success", async () => {
    const { result } = renderHook(() => usePartners(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items).toHaveLength(1);
    expect(result.current.data?.items[0].name).toBe("Acme Corp");
  });

  it("sends the types param as repeated keys", async () => {
    const requestedUrls: string[] = [];
    server.use(
      http.get("/api/v1/partners", ({ request }) => {
        requestedUrls.push(request.url);
        return HttpResponse.json({ items: [mockPartner], total: 1 });
      }),
    );

    renderHook(() => usePartners({ types: ["SUPPLIER", "MANUFACTURER"] }), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(requestedUrls).toHaveLength(1));

    const url = new URL(requestedUrls[0]);
    expect(url.searchParams.getAll("types")).toEqual([
      "SUPPLIER",
      "MANUFACTURER",
    ]);
  });

  it("does not fetch when module is disabled", () => {
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: [],
      isModuleEnabled: () => false,
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });

    const { result } = renderHook(() => usePartners(), {
      wrapper: createWrapper(),
    });
    expect(result.current.isFetching).toBe(false);
    expect(result.current.data).toBeUndefined();
  });

  it("returns error on API failure", async () => {
    server.use(
      http.get("/api/v1/partners", () =>
        HttpResponse.json({ detail: "Forbidden" }, { status: 403 }),
      ),
    );

    const { result } = renderHook(() => usePartners(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useCreatePartner", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.post("/api/v1/partners", () =>
        HttpResponse.json(mockPartner, { status: 201 }),
      ),
    );
  });

  it("creates a partner on success", async () => {
    const { result } = renderHook(() => useCreatePartner(), {
      wrapper: createWrapper(),
    });
    act(() =>
      result.current.mutate({
        name: "Acme Corp",
        type: "SUPPLIER",
        is_consumer: false,
      }),
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.name).toBe("Acme Corp");
  });

  it("returns error on validation failure", async () => {
    server.use(
      http.post("/api/v1/partners", () =>
        HttpResponse.json({ detail: "Name already exists" }, { status: 409 }),
      ),
    );

    const { result } = renderHook(() => useCreatePartner(), {
      wrapper: createWrapper(),
    });
    act(() =>
      result.current.mutate({
        name: "Duplicate",
        type: "SUPPLIER",
        is_consumer: false,
      }),
    );
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useUpdatePartner", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.put("/api/v1/partners/p1", () =>
        HttpResponse.json({ ...mockPartner, name: "Updated Corp" }),
      ),
    );
  });

  it("updates a partner on success", async () => {
    const { result } = renderHook(() => useUpdatePartner(), {
      wrapper: createWrapper(),
    });
    act(() =>
      result.current.mutate({ id: "p1", data: { name: "Updated Corp" } }),
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});

describe("useDeactivatePartner", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.patch("/api/v1/partners/p1/deactivate", () =>
        HttpResponse.json({ ...mockPartner, is_active: false }),
      ),
    );
  });

  it("deactivates a partner on success", async () => {
    const { result } = renderHook(() => useDeactivatePartner(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate("p1"));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});

describe("useActivatePartner", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.patch("/api/v1/partners/p1/activate", () =>
        HttpResponse.json({ ...mockPartner, is_active: true }),
      ),
    );
  });

  it("activates a partner on success", async () => {
    const { result } = renderHook(() => useActivatePartner(), {
      wrapper: createWrapper(),
    });
    act(() => result.current.mutate("p1"));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});
