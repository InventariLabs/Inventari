import React from "react";
import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation, useNavigationType } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";

import { useEquipmentForm } from "../hooks/useEquipmentForm";

/**
 * Adding an asset used to end on the equipment overview with a toast and
 * nothing else: the asset just added was a search away. Now a single asset
 * opens on its own page and a batch on the list that holds it.
 */
vi.mock("@/lib/api/items", () => ({
  itemsApi: {
    getById: vi.fn(),
    create: vi.fn().mockResolvedValue({ id: "new-1", name: "x" }),
    update: vi.fn(),
    uploadImage: vi.fn(),
    deleteImage: vi.fn(),
  },
}));
vi.mock("@/lib/api/labels", () => ({
  labelsApi: {
    assignToExistingItem: vi.fn(),
    unassign: vi.fn(),
    createFromCodes: vi.fn(),
    exportPng: vi.fn(),
  },
}));
vi.mock("@/modules/equipment/api/equipment", () => ({
  equipmentApi: {
    bulkCreateItems: vi.fn().mockResolvedValue({
      created: 2,
      failed: 0,
      items: ["i1", "i2"],
      errors: [],
    }),
  },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

let where = "";
let how = "";
function Probe() {
  where = useLocation().pathname;
  how = useNavigationType();
  return null;
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/equipment/add"]}>
        <Probe />
        {children}
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("where adding an asset lands", () => {
  it("opens the asset it just created", async () => {
    const { result } = renderHook(() => useEquipmentForm(undefined, {}), {
      wrapper,
    });
    act(() => {
      result.current.set("name", "Laptop");
      result.current.set("location_id", "loc-1");
    });

    await act(async () => {
      await result.current.handleSubmit({
        preventDefault: vi.fn(),
      } as unknown as React.FormEvent);
    });

    expect(where).toBe("/equipment/new-1");
    // Back from the new asset must not reopen the form that was just saved.
    expect(how).toBe("REPLACE");
  });

  it("opens the asset list after a batch", async () => {
    const { result } = renderHook(() => useEquipmentForm(undefined, {}), {
      wrapper,
    });
    act(() => {
      result.current.set("location_id", "loc-1");
    });

    await act(async () => {
      await result.current.handleBulkSubmit(
        [{ serial_number: "SN-1" }, { serial_number: "SN-2" }],
        { assignLabels: false, qrOnly: false },
      );
    });

    expect(where).toBe("/equipment/assets");
    expect(how).toBe("REPLACE");
  });
});
