import React from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { useEquipmentForm } from "../hooks/useEquipmentForm";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const LAPTOPS = {
  id: "cat-laptops",
  name: "Laptops",
  context_tag: "equipment",
  parent_id: null,
  organization_id: "org-1",
};

function renderForm() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter>{children}</MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
  return renderHook(() => useEquipmentForm(undefined, {}), { wrapper });
}

/**
 * The single asset and the batch are two submits of one form, and they ask
 * for the same fields: once the organization has an equipment category, a
 * batch of serial numbers is refused without one exactly as a single asset
 * is, before anything is sent.
 */
describe("useEquipmentForm — a batch asks for the category as one asset does", () => {
  it("refuses a batch without a category, and sends it once one is chosen", async () => {
    const batches: unknown[] = [];
    server.use(
      http.get("/api/v1/categories", () =>
        HttpResponse.json(onePage([LAPTOPS])),
      ),
      http.post("/api/v1/equipment/items/bulk", async ({ request }) => {
        batches.push(await request.json());
        return HttpResponse.json({
          created: 1,
          failed: 0,
          items: ["a1"],
          errors: [],
        });
      }),
    );
    const { result } = renderForm();
    await waitFor(() => expect(result.current.categoryRequired).toBe(true));
    act(() => result.current.set("location_id", "loc-1"));

    await act(async () => {
      await result.current.handleBulkSubmit([{ serial_number: "SN-1" }]);
    });

    expect(result.current.fieldErrors.category_id).toBe("Category is required");
    expect(batches).toEqual([]);

    act(() => result.current.set("category_id", LAPTOPS.id));
    await act(async () => {
      await result.current.handleBulkSubmit([{ serial_number: "SN-1" }]);
    });

    await waitFor(() => expect(batches).toHaveLength(1));
    expect(batches[0]).toMatchObject({ category_id: LAPTOPS.id });
  });
});
