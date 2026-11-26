import React from "react";
import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useEquipmentBulkCreate } from "../hooks/useEquipmentBulkCreate";
import { equipmentApi } from "@/modules/equipment/api/equipment";
import { labelsApi } from "@/lib/api/labels";
import { queryKeys } from "@/hooks/queries/keys";
import type { EquipmentFormData } from "@/modules/equipment/pages/AddEquipmentPage";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/modules/equipment/api/equipment", () => ({
  equipmentApi: { bulkCreateItems: vi.fn() },
}));

vi.mock("@/lib/api/labels", () => ({
  labelsApi: {
    createFromCodes: vi.fn(),
    assignToExistingItem: vi.fn(),
  },
}));

function renderBulkCreate() {
  const queryClient = new QueryClient();
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  const form = {
    name: "Laptop",
    location_id: "loc-1",
    category_id: "",
    purchase_price: "",
  } as unknown as EquipmentFormData;
  const { result } = renderHook(
    () =>
      useEquipmentBulkCreate(
        form,
        () => ({}),
        () => true,
      ),
    {
      wrapper: ({ children }: { children: React.ReactNode }) => (
        <MemoryRouter>
          <QueryClientProvider client={queryClient}>
            {children}
          </QueryClientProvider>
        </MemoryRouter>
      ),
    },
  );
  const refreshed = () =>
    invalidate.mock.calls.map((call) => call[0]?.queryKey);
  return { result, refreshed };
}

const entries = [{ serial_number: "SN-1" }, { serial_number: "SN-2" }];

/**
 * The overview tiles read the dashboard and the list reads the assets: a batch
 * add owes both, whether or not labels were asked for.
 */
describe("useEquipmentBulkCreate — what a batch add refreshes", () => {
  beforeEach(() => {
    vi.mocked(equipmentApi.bulkCreateItems).mockResolvedValue({
      created: 2,
      failed: 0,
      items: ["i-1", "i-2"],
      errors: [],
    });
    vi.mocked(labelsApi.createFromCodes).mockResolvedValue([
      { id: "l-1", short_code: "SN-1" },
      { id: "l-2", short_code: "SN-2" },
    ] as never);
  });

  it.each([
    ["without labels", undefined],
    ["with labels", { assignLabels: true }],
  ])("refreshes the overview counts %s", async (_name, options) => {
    const { result, refreshed } = renderBulkCreate();

    await act(() => result.current.handleBulkSubmit(entries, options));

    expect(refreshed()).toContainEqual(queryKeys.equipment.dashboard);
    expect(refreshed()).toContainEqual(queryKeys.equipment.all);
  });
});
