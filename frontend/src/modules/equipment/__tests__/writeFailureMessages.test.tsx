import React from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";

import { server } from "@/test/mocks/server";
import {
  useCheckout,
  useCheckin,
  useCreateMaintenanceLog,
  useBulkReturnEquipment,
  useBulkEditAssets,
} from "@/modules/equipment/hooks/useEquipment";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

/**
 * What five equipment modals say when the save is refused.
 *
 * A 500 from FastAPI arrives as `{"detail": "Internal Server Error"}`, and
 * the reader used to get it verbatim — English, technical, and no use to
 * anyone in any language. `extractApiError` now withholds a 5xx `detail`,
 * which left these five falling back to the shared "The action could not be
 * completed.": true, and no help in a modal that could say which action.
 *
 * Business rules still speak for themselves — a 4xx carries a sentence
 * written to be read, and the last case here pins that it survives.
 */
const wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider
    client={
      new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      })
    }
  >
    {children}
  </QueryClientProvider>
);

const serverError = () =>
  HttpResponse.json({ detail: "Internal Server Error" }, { status: 500 });

const CASES = [
  {
    name: "check-out",
    handler: http.post("/api/v1/equipment/assignments", serverError),
    hook: useCheckout,
    vars: { item_id: "i-1", assigned_to_name: "Marta" },
    message: "Failed to check the asset out",
  },
  {
    name: "check-in",
    handler: http.post(
      "/api/v1/equipment/assignments/a-1/checkin",
      serverError,
    ),
    hook: useCheckin,
    vars: { assignmentId: "a-1", data: { checkin_condition: "GOOD" } },
    message: "Failed to return the asset",
  },
  {
    name: "service entry",
    handler: http.post("/api/v1/equipment/maintenance", serverError),
    hook: useCreateMaintenanceLog,
    vars: { item_id: "i-1", maintenance_type: "REPAIR", title: "Fan" },
    message: "Failed to add the service entry",
  },
  {
    name: "bulk return",
    handler: http.post("/api/v1/equipment/items/bulk-return", serverError),
    hook: useBulkReturnEquipment,
    vars: { item_ids: ["i-1"], checkin_condition: "GOOD" },
    message: "Failed to return the selected assets",
  },
  {
    name: "bulk change",
    handler: http.patch("/api/v1/equipment/assets/bulk", serverError),
    hook: useBulkEditAssets,
    vars: {
      item_ids: ["i-1"],
      action: "change_status",
      data: { status: "AVAILABLE" },
    },
    message: "Failed to change the selected assets",
  },
] as const;

beforeEach(() => {
  vi.clearAllMocks();
  server.resetHandlers();
});

describe("a refused equipment write says which write", () => {
  it.each(CASES)("$name", async ({ handler, hook, vars, message }) => {
    server.use(handler);

    const { result } = renderHook(() => hook(), { wrapper });
    (result.current.mutate as (v: unknown) => void)(vars);

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(message));
  });

  it("still hands over what a business rule had to say", async () => {
    server.use(
      http.post("/api/v1/equipment/assignments", () =>
        HttpResponse.json(
          { detail: "This asset is already checked out." },
          { status: 409 },
        ),
      ),
    );

    const { result } = renderHook(() => useCheckout(), { wrapper });
    result.current.mutate({ item_id: "i-1", assigned_to_name: "Marta" });

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "This asset is already checked out.",
      ),
    );
  });
});
