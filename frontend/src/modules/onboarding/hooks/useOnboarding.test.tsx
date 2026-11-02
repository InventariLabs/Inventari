import { renderHook, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import React from "react";
import {
  useProfileSwitchPreview,
  useProfileSwitchApply,
  useProfiles,
} from "./useOnboarding";
import type { ProductProfile, ProfileSwitchResponse } from "@/types";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

const profiles: ProductProfile[] = [
  {
    id: "food_home",
    name: "Food & Home",
    description: "d",
    default_modules: ["items"],
    seed_profile: "food_home",
    launcher_categories: { items: "business" },
  },
  {
    id: "equipment_wms",
    name: "Equipment & Warehouse",
    description: "d",
    default_modules: ["items", "equipment"],
    seed_profile: "equipment_wms",
    launcher_categories: { items: "business", equipment: "business" },
  },
];

const diffResponse: ProfileSwitchResponse = {
  applied: false,
  diff: {
    disable_all: [],
    from_profile_id: "food_home",
    to_profile_id: "equipment_wms",
    enable: ["equipment"],
    disable: [],
    cascade_disable: [],
    unchanged: ["items"],
    manual_kept: [],
    final_enabled_modules: ["items", "equipment"],
    module_config_overwrite: ["equipment"],
    warnings: [],
    offer_location_renumbering: false,
  },
};

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
}

describe("useProfiles", () => {
  it("fetches the list of available profiles", async () => {
    server.use(
      http.get("*/api/v1/profiles", () => HttpResponse.json(onePage(profiles))),
    );
    const { result } = renderHook(() => useProfiles(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(profiles);
  });
});

describe("useProfileSwitchPreview", () => {
  it("sends dry_run=true and returns the diff", async () => {
    let captured: Record<string, unknown> | null = null;
    server.use(
      http.post("*/api/v1/onboarding/switch-profile", async ({ request }) => {
        captured = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(diffResponse);
      }),
    );
    const { result } = renderHook(() => useProfileSwitchPreview(), {
      wrapper: makeWrapper(),
    });
    result.current.mutate("equipment_wms");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(captured).toEqual({
      profile_id: "equipment_wms",
      dry_run: true,
    });
    expect(result.current.data?.applied).toBe(false);
    expect(result.current.data?.diff.enable).toEqual(["equipment"]);
  });
});

describe("useProfileSwitchApply", () => {
  it("sends dry_run=false and returns applied=true", async () => {
    let captured: Record<string, unknown> | null = null;
    const applyResponse: ProfileSwitchResponse = {
      ...diffResponse,
      applied: true,
    };
    server.use(
      http.post("*/api/v1/onboarding/switch-profile", async ({ request }) => {
        captured = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(applyResponse);
      }),
    );
    const { result } = renderHook(() => useProfileSwitchApply(), {
      wrapper: makeWrapper(),
    });
    result.current.mutate("equipment_wms");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(captured).toEqual({
      profile_id: "equipment_wms",
      dry_run: false,
    });
    expect(result.current.data?.applied).toBe(true);
  });
});
