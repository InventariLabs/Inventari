import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { useAssetImage } from "@/modules/equipment/hooks/useAssetImage";
import { equipmentApi } from "@/modules/equipment/api/equipment";
import type { Item } from "@/types";

vi.mock("@/modules/equipment/api/equipment", () => ({
  equipmentApi: { listModels: vi.fn() },
}));

vi.mock("@/contexts/ModulesContext", async () => {
  const actual = await vi.importActual<Record<string, unknown>>(
    "@/contexts/ModulesContext",
  );
  return {
    ...actual,
    useModules: () => ({
      isModuleEnabled: () => true,
      enabledModules: ["equipment"],
    }),
  };
});

const MODEL = {
  id: "model-1",
  name: "Latitude 5540",
  image_url: "https://files/model.png",
  equipment_meta: {},
  category_id: null,
  brand: null,
  description: null,
};

function asset(overrides: Partial<Item>): Item {
  return {
    id: "item-1",
    name: "Laptop",
    image_url: null,
    metadata: {},
    ...overrides,
  } as unknown as Item;
}

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={client}>
      <ModulesProvider>{children}</ModulesProvider>
    </QueryClientProvider>
  );
}

describe("an asset without its own picture", () => {
  beforeEach(() => {
    vi.mocked(equipmentApi.listModels).mockResolvedValue([MODEL] as never);
  });

  it("shows the picture of the model it was created from", async () => {
    const { result } = renderHook(() => useAssetImage(), { wrapper });

    await waitFor(() => {
      expect(
        result.current(
          asset({ metadata: { equipment: { model_id: "model-1" } } }),
        ),
      ).toEqual({ url: "https://files/model.png", fromModel: true });
    });
  });

  it("prefers its own picture over the model's", async () => {
    const { result } = renderHook(() => useAssetImage(), { wrapper });

    await waitFor(() => expect(equipmentApi.listModels).toHaveBeenCalled());

    expect(
      result.current(
        asset({
          image_url: "https://files/own.png",
          metadata: { equipment: { model_id: "model-1" } },
        }),
      ),
    ).toEqual({ url: "https://files/own.png", fromModel: false });
  });

  it("shows nothing when it belongs to no model", async () => {
    const { result } = renderHook(() => useAssetImage(), { wrapper });

    await waitFor(() => expect(equipmentApi.listModels).toHaveBeenCalled());

    expect(result.current(asset({}))).toBeNull();
  });
});
