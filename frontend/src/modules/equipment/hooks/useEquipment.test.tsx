import React from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  useEquipmentDashboard,
  useActiveAssignments,
  useItemAssignmentHistory,
  useDeleteMaintenanceLog,
  useCreateCampaign,
  useScopePreview,
  useCreateEquipmentModel,
  useUpdateEquipmentModel,
  useDeleteEquipmentModel,
  useCloneEquipmentModel,
  useRetireEquipment,
  useArchiveEquipment,
  usePurgeEquipment,
  useRestoreEquipment,
  useBulkArchiveEquipment,
  useRetireMatchingAssets,
  useArchiveMatchingAssets,
  useBulkPurgeEquipment,
  useEquipmentImportExecute,
} from "./useEquipment";
import { queryKeys } from "@/hooks/queries/keys";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mockDashboard = {
  total_assets: 10,
  active_assignments: 3,
  in_maintenance: 1,
  retired: 0,
  by_status: {},
  by_category: [],
  recent_activity: [],
  warranty_alerts: [],
};

const mockAssignments = [
  {
    id: "asg-1",
    item_id: "item-1",
    item_name: "Dell Laptop",
    assignee_partner_id: null,
    partner_name: null,
    assigned_to_name: "John Doe",
    assigned_to_email: "john@example.com",
    checked_out_at: "2024-01-01T00:00:00Z",
    expected_return_at: null,
    checked_in_at: null,
    checked_out_by: "user-1",
    checked_in_by: null,
    checkout_notes: null,
    checkin_notes: null,
    checkin_condition: null,
    created_at: "2024-01-01T00:00:00Z",
  },
];

const createWrapper = (
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  }),
) => {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <BrowserRouter>{children}</BrowserRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
};

describe("useEquipmentDashboard", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/equipment/dashboard", () =>
        HttpResponse.json(mockDashboard),
      ),
    );
  });

  it("returns dashboard data on success", async () => {
    const { result } = renderHook(() => useEquipmentDashboard(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.total_assets).toBe(10);
    expect(result.current.data?.active_assignments).toBe(3);
  });
});

describe("useActiveAssignments", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/equipment/assignments", () =>
        HttpResponse.json({
          items: mockAssignments,
          total: mockAssignments.length,
          limit: 50,
          offset: 0,
          has_more: false,
        }),
      ),
    );
  });

  it("returns the paginated active assignments response", async () => {
    const { result } = renderHook(() => useActiveAssignments(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.total).toBe(1);
    expect(result.current.data?.items[0].item_name).toBe("Dell Laptop");
  });
});

describe("useItemAssignmentHistory", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/equipment/assignments/item/item-1", () =>
        HttpResponse.json(onePage(mockAssignments)),
      ),
    );
  });

  it("returns assignment history for a given item", async () => {
    const { result } = renderHook(() => useItemAssignmentHistory("item-1"), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
  });

  it("does not fetch when itemId is empty", async () => {
    const { result } = renderHook(() => useItemAssignmentHistory(""), {
      wrapper: createWrapper(),
    });
    expect(result.current.isLoading).toBe(false);
    expect(result.current.data).toBeUndefined();
  });
});

interface SentRequest {
  method: string;
  path: string;
  search: string;
  body: unknown;
}

/**
 * Every write the asset screens make goes through one of these hooks. Each
 * row names the hook, what it is called with, and the request it must send.
 * The test catches a hook pointed at the wrong endpoint or verb, a payload
 * that lost its shape on the way, and — the failure the reader actually
 * meets — a write that does not mark the cached asset list stale, so the
 * list keeps showing the asset as it was before the click.
 */
const writes: {
  name: string;
  use: () => { mutateAsync: (vars: never) => Promise<unknown> };
  vars: unknown;
  method: string;
  path: string;
  search?: string;
  body?: unknown;
}[] = [
  {
    name: "useDeleteMaintenanceLog",
    use: useDeleteMaintenanceLog,
    vars: "log-1",
    method: "DELETE",
    path: "/api/v1/equipment/maintenance/log-1",
  },
  {
    name: "useCreateCampaign",
    use: useCreateCampaign,
    vars: { name: "Q4 check", scope_type: "ALL" },
    method: "POST",
    path: "/api/v1/equipment/campaigns",
    body: { name: "Q4 check", scope_type: "ALL" },
  },
  {
    name: "useCreateEquipmentModel",
    use: useCreateEquipmentModel,
    vars: { name: "ThinkPad T14" },
    method: "POST",
    path: "/api/v1/equipment/models",
    body: { name: "ThinkPad T14" },
  },
  {
    name: "useUpdateEquipmentModel",
    use: useUpdateEquipmentModel,
    vars: { modelId: "model-1", data: { name: "ThinkPad T14s" } },
    method: "PUT",
    path: "/api/v1/equipment/models/model-1",
    body: { name: "ThinkPad T14s" },
  },
  {
    name: "useDeleteEquipmentModel",
    use: useDeleteEquipmentModel,
    vars: "model-1",
    method: "DELETE",
    path: "/api/v1/equipment/models/model-1",
  },
  {
    name: "useCloneEquipmentModel",
    use: useCloneEquipmentModel,
    vars: "model-1",
    method: "POST",
    path: "/api/v1/equipment/models/model-1/clone",
  },
  {
    name: "useRetireEquipment",
    use: useRetireEquipment,
    vars: "item-1",
    method: "POST",
    path: "/api/v1/equipment/items/item-1/retire",
  },
  {
    name: "useArchiveEquipment",
    use: useArchiveEquipment,
    vars: "item-1",
    method: "POST",
    path: "/api/v1/equipment/items/item-1/archive",
  },
  {
    name: "usePurgeEquipment",
    use: usePurgeEquipment,
    vars: { itemId: "item-1", reason: "duplicate" },
    method: "DELETE",
    path: "/api/v1/items/item-1/purge",
    search: "?reason=duplicate",
  },
  {
    name: "useRestoreEquipment",
    use: useRestoreEquipment,
    vars: "item-1",
    method: "POST",
    path: "/api/v1/items/item-1/restore",
  },
  {
    name: "useBulkArchiveEquipment",
    use: useBulkArchiveEquipment,
    vars: ["item-1", "item-2"],
    method: "POST",
    path: "/api/v1/equipment/items/bulk-archive",
    body: ["item-1", "item-2"],
  },
  {
    name: "useRetireMatchingAssets",
    use: useRetireMatchingAssets,
    vars: { status: "AVAILABLE", location_id: "loc-1" },
    method: "POST",
    path: "/api/v1/equipment/assets/matching/retire",
    body: { status: "AVAILABLE", location_id: "loc-1" },
  },
  {
    name: "useArchiveMatchingAssets",
    use: useArchiveMatchingAssets,
    vars: { search: "dell" },
    method: "POST",
    path: "/api/v1/equipment/assets/matching/archive",
    body: { search: "dell" },
  },
  {
    name: "useBulkPurgeEquipment",
    use: useBulkPurgeEquipment,
    vars: ["item-1"],
    method: "POST",
    path: "/api/v1/equipment/items/bulk-purge",
    body: ["item-1"],
  },
];

describe("equipment writes reach their endpoint and leave the asset list stale", () => {
  let sent: SentRequest[];

  beforeEach(() => {
    sent = [];
    server.use(
      http.all("/api/v1/*", async ({ request }) => {
        const url = new URL(request.url);
        const text = request.method === "GET" ? "" : await request.text();
        sent.push({
          method: request.method,
          path: url.pathname,
          search: url.search,
          body: text ? JSON.parse(text) : undefined,
        });
        return HttpResponse.json({});
      }),
    );
  });

  it.each(writes)("$name", async (row) => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => row.use(), {
      wrapper: createWrapper(queryClient),
    });
    await act(() => result.current.mutateAsync(row.vars as never));

    const write = sent.find((r) => r.method === row.method);
    expect(write).toEqual({
      method: row.method,
      path: row.path,
      search: row.search ?? "",
      body: row.body,
    });
    // ["equipment"] is the prefix of every asset list key, so this is the
    // call that marks the list on screen stale.
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: queryKeys.equipment.all,
    });
  });

  it("sends an import's file, mapping and defaults as one form", async () => {
    let form = "";
    server.use(
      http.post("/api/v1/equipment/import/execute", async ({ request }) => {
        form = await request.text();
        return HttpResponse.json({ created: 1, errors: [] });
      }),
    );
    const { result } = renderHook(() => useEquipmentImportExecute(), {
      wrapper: createWrapper(),
    });
    const file = new File(["name\nDell"], "assets.csv", { type: "text/csv" });
    await act(() =>
      result.current.mutateAsync({
        file,
        mapping: { Name: "name" },
        defaultLocationId: "loc-1",
        defaultCategoryId: "cat-1",
      }),
    );
    // The multipart body, read as text: one part per field.
    const part = (name: string) =>
      new RegExp(
        `name="${name}"[^\\r\\n]*\\r?\\n(?:[^\\r\\n]+\\r?\\n)*\\r?\\n([^\\r\\n]*)`,
      ).exec(form)?.[1];
    // jsdom drops a File's name on the way into the body; the part and its
    // type are what survive.
    expect(form).toMatch(/name="file".*\r?\nContent-Type: text\/csv/);
    expect(JSON.parse(part("mapping_json") ?? "null")).toEqual({
      Name: "name",
    });
    expect(part("default_location_id")).toBe("loc-1");
    expect(part("default_category_id")).toBe("cat-1");
  });
});

describe("useScopePreview", () => {
  it("asks for the count of a narrowed scope with its filter", async () => {
    let asked: URLSearchParams | null = null;
    server.use(
      http.get("/api/v1/equipment/campaigns/scope-preview", ({ request }) => {
        asked = new URL(request.url).searchParams;
        return HttpResponse.json({ assets: 4, people: 2 });
      }),
    );
    const { result } = renderHook(() => useScopePreview("CATEGORY", "cat-1"), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const params = asked as unknown as URLSearchParams;
    expect(params.get("scope_type")).toBe("CATEGORY");
    expect(params.get("scope_filter_id")).toBe("cat-1");
  });

  it("does not ask for a narrowed scope that has no filter yet", async () => {
    const asked = vi.fn();
    server.use(
      http.get("/api/v1/equipment/campaigns/scope-preview", () => {
        asked();
        return HttpResponse.json({ assets: 99, people: 9 });
      }),
    );
    const { result } = renderHook(() => useScopePreview("CATEGORY"), {
      wrapper: createWrapper(),
    });
    await new Promise((r) => setTimeout(r, 50));
    expect(asked).not.toHaveBeenCalled();
    expect(result.current.data).toBeUndefined();
  });
});
