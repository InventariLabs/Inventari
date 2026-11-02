import React from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";

import { useEquipmentForm } from "../hooks/useEquipmentForm";
import {
  filterDedicatedFields,
  DEDICATED_KEYS,
} from "../hooks/useEquipmentForm";
import { itemsApi } from "@/lib/api/items";
import { labelsApi } from "@/lib/api/labels";
import { equipmentApi } from "@/modules/equipment/api/equipment";
import type { Item, FieldDefinition } from "@/types";

// Minimal but fully-typed Item for getById mocks, with per-test overrides.
function mockItem(overrides: Partial<Item> = {}): Item {
  return {
    id: "edit-1",
    location_id: "loc-1",
    category_id: "c1",
    name: "Laptop",
    brand: null,
    description: null,
    weight: null,
    quantity: "1",
    added_date: "2024-01-01T00:00:00Z",
    expiry_date: null,
    freeze_date: null,
    shelf_location: null,
    image_url: null,
    metadata: { equipment: {} },
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    is_deleted: false,
    ...overrides,
  };
}

// Stub the API layer so the test exercises the form's orchestration logic
// (in particular, the post-save query invalidation) without a network layer.
vi.mock("@/lib/api/items", () => ({
  itemsApi: {
    getById: vi.fn().mockResolvedValue({
      id: "i1",
      name: "x",
      category_id: "c1",
      location_id: "loc-1",
      metadata: { equipment: {} },
      image_url: null,
    }),
    create: vi.fn().mockResolvedValue({ id: "new-1", name: "x" }),
    update: vi.fn().mockResolvedValue({ id: "edit-1" }),
    uploadImage: vi.fn().mockResolvedValue({ image_url: "/uploads/x.png" }),
    deleteImage: vi.fn().mockResolvedValue(undefined),
  },
}));
vi.mock("@/lib/api/labels", () => ({
  labelsApi: {
    assignToExistingItem: vi.fn().mockResolvedValue(undefined),
    unassign: vi.fn().mockResolvedValue(undefined),
    // Echo each requested code back as a LabelPool so the assign step can use
    // the serial as the short_code (mirrors the real from-codes endpoint).
    createFromCodes: vi
      .fn()
      .mockImplementation((data: { codes: { short_code: string }[] }) =>
        data.codes.map((c, i) => ({
          id: `l${i + 1}`,
          short_code: c.short_code,
        })),
      ),
    exportPng: vi
      .fn()
      .mockResolvedValue(new Blob(["png"], { type: "image/png" })),
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

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/equipment/add"]}>
        {children}
      </MemoryRouter>
    </QueryClientProvider>
  );
  return { qc, Wrapper };
}

describe("useEquipmentForm — dedicated date fields", () => {
  it("DEDICATED_KEYS covers purchase_date, warranty_until and notes", () => {
    expect([...DEDICATED_KEYS].sort()).toEqual([
      "notes",
      "purchase_date",
      "warranty_until",
    ]);
  });

  it("filterDedicatedFields drops fields owned by the dedicated cards", () => {
    const fields = [
      {
        key: "purchase_date",
        type: "date",
        label: "Purchase Date",
        visible: true,
      },
      {
        key: "warranty_until",
        type: "date",
        label: "Warranty Until",
        visible: true,
      },
      { key: "notes", type: "textarea", label: "Notes", visible: true },
      {
        key: "serial_number",
        type: "text",
        label: "Serial Number",
        visible: true,
      },
    ] as FieldDefinition[];
    expect(filterDedicatedFields(fields).map((f) => f.key)).toEqual([
      "serial_number",
    ]);
  });

  it("buildMeta prefers the Purchase & Warranty card over dynamic values", async () => {
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useEquipmentForm(undefined, {}), {
      wrapper: Wrapper,
    });

    act(() => {
      result.current.set("name", "Laptop");
      result.current.set("location_id", "loc-1");
      result.current.setDynamic("purchase_date", "2024-02-01");
      result.current.setDynamic("warranty_until", "2025-01-01");
      result.current.set("purchase_date", "2025-04-03");
      result.current.set("warranty_until", "2026-06-01");
    });

    await act(async () => {
      await result.current.handleSubmit({
        preventDefault: vi.fn(),
      } as unknown as React.FormEvent);
    });

    const payload = vi.mocked(itemsApi.create).mock.calls[0][0] as unknown as {
      metadata: { equipment: Record<string, unknown> };
    };
    const meta = payload.metadata.equipment;
    expect(meta.purchase_date).toBe("2025-04-03");
    expect(meta.warranty_until).toBe("2026-06-01");
  });
});

describe("useEquipmentForm — a unit remembers the model it came from", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const MODEL = {
    id: "model-1",
    name: "Latitude 5540",
    brand: "Dell",
    description: null,
    image_url: "https://files/model.png",
    category_id: "c1",
    category_name: null,
    equipment_meta: { manufacturer: "Dell" },
  };

  it("sends the model id, so the unit can fall back to its picture", async () => {
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useEquipmentForm(undefined, {}), {
      wrapper: Wrapper,
    });

    act(() => {
      result.current.handleModelSelect([MODEL], "model-1");
      result.current.set("location_id", "loc-1");
    });

    await act(async () => {
      await result.current.handleSubmit({
        preventDefault: vi.fn(),
      } as unknown as React.FormEvent);
    });

    const payload = vi.mocked(itemsApi.create).mock.calls[0][0] as unknown as {
      metadata?: { equipment: Record<string, unknown> };
    };
    expect(payload.metadata?.equipment.model_id).toBe("model-1");
  });

  it("releases it when the form goes back to creating from scratch", async () => {
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useEquipmentForm(undefined, {}), {
      wrapper: Wrapper,
    });

    act(() => {
      result.current.handleModelSelect([MODEL], "model-1");
    });
    act(() => {
      result.current.handleModelSelect([MODEL], "");
      result.current.set("name", "Laptop");
      result.current.set("location_id", "loc-1");
    });

    await act(async () => {
      await result.current.handleSubmit({
        preventDefault: vi.fn(),
      } as unknown as React.FormEvent);
    });

    const payload = vi.mocked(itemsApi.create).mock.calls[0][0] as unknown as {
      metadata?: { equipment: Record<string, unknown> };
    };
    expect(payload.metadata?.equipment).not.toHaveProperty("model_id");
  });
});

describe("useEquipmentForm — a chosen model fills what the model defines", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const MODEL = {
    id: "model-1",
    name: "Latitude 5540",
    brand: "Dell",
    description: null,
    image_url: null,
    category_id: "c1",
    category_name: null,
    equipment_meta: { cpu: "i5" },
  };

  it("fills the name, the category, the manufacturer and the model", () => {
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useEquipmentForm(undefined, {}), {
      wrapper: Wrapper,
    });

    act(() => {
      result.current.handleModelSelect([MODEL], "model-1");
    });

    expect(result.current.form.name).toBe("Dell Latitude 5540");
    expect(result.current.form.category_id).toBe("c1");
    expect(result.current.form.dynamic.manufacturer).toBe("Dell");
    expect(result.current.form.dynamic.model).toBe("Latitude 5540");
    expect(result.current.form.dynamic.cpu).toBe("i5");
  });

  it("keeps the model's own meta over the brand and name", () => {
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useEquipmentForm(undefined, {}), {
      wrapper: Wrapper,
    });

    act(() => {
      result.current.handleModelSelect(
        [{ ...MODEL, equipment_meta: { manufacturer: "Dell Inc." } }],
        "model-1",
      );
    });

    expect(result.current.form.dynamic.manufacturer).toBe("Dell Inc.");
  });

  it("does not leave the category reset suppressed when the model names no category", () => {
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useEquipmentForm(undefined, {}), {
      wrapper: Wrapper,
    });

    act(() => {
      result.current.handleModelSelect(
        [{ ...MODEL, category_id: null }],
        "model-1",
      );
    });
    act(() => {
      result.current.set("category_id", "c2");
    });

    // The model's fields belong to no category the user has now chosen.
    expect(result.current.form.dynamic).toEqual({});
  });
});

describe("useEquipmentForm — a new asset is always filterable", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("sends the equipment namespace even when the category declares no fields", async () => {
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useEquipmentForm(undefined, {}), {
      wrapper: Wrapper,
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

    const payload = vi.mocked(itemsApi.create).mock.calls[0][0] as unknown as {
      metadata?: { equipment: Record<string, unknown> };
    };
    // The namespace is what the module's interceptor seeds the status from;
    // without it the asset carries no status and hides from every chip.
    expect(payload.metadata?.equipment).toEqual({});
  });
});

describe("useEquipmentForm — the serial number has one home", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("sends it as the core field, not inside the equipment namespace", async () => {
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useEquipmentForm(undefined, {}), {
      wrapper: Wrapper,
    });

    act(() => {
      result.current.set("name", "Laptop");
      result.current.set("location_id", "loc-1");
      result.current.setDynamic("serial_number", "SN-FORM-1");
      result.current.setDynamic("asset_tag", "AT-1");
    });

    await act(async () => {
      await result.current.handleSubmit({
        preventDefault: vi.fn(),
      } as unknown as React.FormEvent);
    });

    const payload = vi.mocked(itemsApi.create).mock.calls[0][0] as unknown as {
      serial_number?: string;
      metadata?: { equipment: Record<string, unknown> };
    };
    expect(payload.serial_number).toBe("SN-FORM-1");
    expect(payload.metadata?.equipment).not.toHaveProperty("serial_number");
    expect(payload.metadata?.equipment.asset_tag).toBe("AT-1");
  });

  it("loads an existing asset's number from the core field", async () => {
    vi.mocked(itemsApi.getById).mockResolvedValueOnce(
      mockItem({ serial_number: "SN-STORED", metadata: { equipment: {} } }),
    );
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useEquipmentForm("edit-1", {}), {
      wrapper: Wrapper,
    });

    await waitFor(() =>
      expect(result.current.form.dynamic.serial_number).toBe("SN-STORED"),
    );

    await act(async () => {
      await result.current.handleSubmit({
        preventDefault: vi.fn(),
      } as unknown as React.FormEvent);
    });

    const payload = vi.mocked(itemsApi.update).mock.calls[0][1] as unknown as {
      serial_number?: string | null;
      metadata?: { equipment: Record<string, unknown> };
    };
    expect(payload.serial_number).toBe("SN-STORED");
    expect(payload.metadata?.equipment).not.toHaveProperty("serial_number");
  });
});

describe("useEquipmentForm — invalidates cache after create + image upload", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("invalidates the equipment assets cache after create + upload", async () => {
    const { qc, Wrapper } = makeWrapper();
    const invalidateSpy = vi.spyOn(qc, "invalidateQueries");

    const { result } = renderHook(() => useEquipmentForm(undefined, {}), {
      wrapper: Wrapper,
    });

    act(() => {
      result.current.set("name", "Laptop");
      result.current.set("location_id", "loc-1");
    });

    const fakeImage = new File(["png-bytes"], "cover.png", {
      type: "image/png",
    });

    act(() => {
      result.current.setImageFile(fakeImage);
    });

    await act(async () => {
      await result.current.handleSubmit({
        preventDefault: vi.fn(),
      } as unknown as React.FormEvent);
    });

    // The fix: after create + upload, the cache must be invalidated for the
    // equipment assets key so the detail page refetches image_url. Before the
    // fix, no invalidation → stale 5-min cache → uploaded image never rendered.
    await waitFor(() => {
      const invalidatedKeys = invalidateSpy.mock.calls.map(
        (c) => (c[0] as { queryKey: readonly unknown[] }).queryKey,
      );
      expect(invalidatedKeys.some((k) => k.includes("assets"))).toBe(true);
    });
  });
});

describe("useEquipmentForm — edit-mode label & barcode persistence", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("reassigns the label via the pool API when the label changes on edit", async () => {
    vi.mocked(itemsApi.getById).mockResolvedValue(
      mockItem({ barcode: "111", label_code: "OLD-123" }),
    );
    const { Wrapper } = makeWrapper();

    const { result } = renderHook(() => useEquipmentForm("edit-1", {}), {
      wrapper: Wrapper,
    });

    await waitFor(() => {
      expect(result.current.form.label_code).toBe("OLD-123");
    });

    act(() => {
      result.current.set("label_code", "NEW-456");
    });

    await act(async () => {
      await result.current.handleSubmit({
        preventDefault: vi.fn(),
      } as unknown as React.FormEvent);
    });

    expect(itemsApi.update).toHaveBeenCalledWith(
      "edit-1",
      expect.objectContaining({ barcode: "111" }),
    );
    expect(labelsApi.assignToExistingItem).toHaveBeenCalledWith(
      "NEW-456",
      "edit-1",
    );
  });

  it("releases the label from the pool when it is cleared on edit", async () => {
    vi.mocked(itemsApi.getById).mockResolvedValue(
      mockItem({ label_code: "OLD-123" }),
    );
    const { Wrapper } = makeWrapper();

    const { result } = renderHook(() => useEquipmentForm("edit-1", {}), {
      wrapper: Wrapper,
    });

    await waitFor(() => {
      expect(result.current.form.label_code).toBe("OLD-123");
    });

    act(() => {
      result.current.set("label_code", "");
    });

    await act(async () => {
      await result.current.handleSubmit({
        preventDefault: vi.fn(),
      } as unknown as React.FormEvent);
    });

    expect(labelsApi.unassign).toHaveBeenCalledWith("OLD-123");
    expect(labelsApi.assignToExistingItem).not.toHaveBeenCalled();
  });

  it("does not touch the label pool when the label is unchanged on edit", async () => {
    vi.mocked(itemsApi.getById).mockResolvedValue(
      mockItem({ barcode: "111", label_code: "KEEP-1" }),
    );
    const { Wrapper } = makeWrapper();

    const { result } = renderHook(() => useEquipmentForm("edit-1", {}), {
      wrapper: Wrapper,
    });

    await waitFor(() => {
      expect(result.current.form.label_code).toBe("KEEP-1");
    });

    await act(async () => {
      await result.current.handleSubmit({
        preventDefault: vi.fn(),
      } as unknown as React.FormEvent);
    });

    expect(labelsApi.assignToExistingItem).not.toHaveBeenCalled();
    expect(labelsApi.unassign).not.toHaveBeenCalled();
  });
});

describe("useEquipmentForm — batch QR label generation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // restore the bulkCreate default after any per-test override
    vi.mocked(equipmentApi.bulkCreateItems).mockResolvedValue({
      created: 2,
      failed: 0,
      items: ["i1", "i2"],
      errors: [],
    });
  });

  it("generates and assigns one QR label per created item when assignLabels is on", async () => {
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useEquipmentForm(undefined, {}), {
      wrapper: Wrapper,
    });

    act(() => {
      result.current.set("location_id", "loc-1");
    });

    await act(async () => {
      await result.current.handleBulkSubmit(
        [{ serial_number: "SN-1" }, { serial_number: "SN-2" }],
        { assignLabels: true, qrOnly: false },
      );
    });

    // Labels are registered from the serials themselves (not random STM codes).
    expect(labelsApi.createFromCodes).toHaveBeenCalledWith({
      codes: [
        { short_code: "SN-1", description: "Asset" },
        { short_code: "SN-2", description: "Asset" },
      ],
      label_type: "EQUIPMENT",
    });
    expect(labelsApi.assignToExistingItem).toHaveBeenCalledTimes(2);
    expect(labelsApi.assignToExistingItem).toHaveBeenCalledWith("SN-1", "i1");
    expect(labelsApi.assignToExistingItem).toHaveBeenCalledWith("SN-2", "i2");
    expect(result.current.bulkLabelResult).toEqual({
      labelIds: ["l1", "l2"],
      count: 2,
      qrOnly: false,
    });
  });

  it("omits the description when qrOnly is on", async () => {
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useEquipmentForm(undefined, {}), {
      wrapper: Wrapper,
    });

    act(() => {
      result.current.set("location_id", "loc-1");
    });

    await act(async () => {
      await result.current.handleBulkSubmit([{ serial_number: "SN-1" }], {
        assignLabels: true,
        qrOnly: true,
      });
    });

    expect(labelsApi.createFromCodes).toHaveBeenCalledWith({
      codes: [{ short_code: "SN-1", description: undefined }],
      label_type: "EQUIPMENT",
    });
    expect(result.current.bulkLabelResult?.qrOnly).toBe(true);
  });

  it("skips label generation when assignLabels is off", async () => {
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useEquipmentForm(undefined, {}), {
      wrapper: Wrapper,
    });

    act(() => {
      result.current.set("location_id", "loc-1");
    });

    await act(async () => {
      await result.current.handleBulkSubmit([{ serial_number: "SN-1" }], {
        assignLabels: false,
      });
    });

    expect(labelsApi.createFromCodes).not.toHaveBeenCalled();
    expect(result.current.bulkLabelResult).toBeNull();
  });

  it("downloadBulkLabels exports a combined PNG for the generated labels", async () => {
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useEquipmentForm(undefined, {}), {
      wrapper: Wrapper,
    });

    act(() => {
      result.current.set("location_id", "loc-1");
    });

    await act(async () => {
      await result.current.handleBulkSubmit(
        [{ serial_number: "SN-1" }, { serial_number: "SN-2" }],
        { assignLabels: true },
      );
    });

    await act(async () => {
      await result.current.downloadBulkLabels();
    });

    expect(labelsApi.exportPng).toHaveBeenCalledWith(
      expect.objectContaining({
        labelIds: ["l1", "l2"],
      }),
    );
  });
});
