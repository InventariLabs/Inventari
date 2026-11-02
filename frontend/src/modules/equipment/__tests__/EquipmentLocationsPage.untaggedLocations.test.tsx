import React, { useState } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { ModulesProvider } from "@/contexts/ModulesContext";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";

import EquipmentLocationsPage from "../pages/EquipmentLocationsPage";
import type { StorageLocation } from "@/types";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const MIXED_LOCATIONS = [
  {
    id: "loc-1",
    location_type_id: null,
    organization_id: "org-1",
    usage: "internal",
    parent_id: null,
    name: "Server Room",
    description: null,
    location_details: null,
    settings: null,
    created_at: "2024-01-01T00:00:00Z",
    context_schema: [],
    behavior_mode: "NONE",
    field_definitions: [],
    context_tag: "equipment",
  },
  {
    id: "loc-2",
    location_type_id: null,
    organization_id: "org-1",
    usage: "internal",
    parent_id: null,
    name: "Biuro Kraków",
    description: "Core storage screen location",
    location_details: null,
    settings: null,
    created_at: "2024-01-01T00:00:00Z",
    context_schema: [],
    behavior_mode: "STOCK",
    field_definitions: [],
    context_tag: null,
  },
] as StorageLocation[];

/**
 * Locations created in the core Storages screen (no context_tag) hold assets
 * but were invisible to the equipment Locations page and unselectable in the
 * add-asset form. So an untagged location an asset stands in must not vanish
 * from here — which is why the scope is `module_scope`, resolved server-side
 * as "tagged for this module, or holding its records", and not a context_tag
 * filter that would lose exactly those.
 */

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  function HeaderHost({ children }: { children: React.ReactNode }) {
    const [data, setData] = useState<PageHeaderData>({});
    return (
      <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
        {children}
      </PageHeaderContext.Provider>
    );
  }

  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter>
          <HeaderHost>{children}</HeaderHost>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
  return render(<EquipmentLocationsPage />, { wrapper });
}

describe("EquipmentLocationsPage — the module's own locations", () => {
  beforeEach(() => {
    server.resetHandlers();
    server.use(
      http.get("/api/v1/locations", ({ request }) => {
        const url = new URL(request.url);
        // Not a context_tag filter: that one drops the untagged locations
        // assets actually stand in, which is the case this file exists for.
        expect(url.searchParams.get("context_tag")).toBeNull();
        expect(url.searchParams.get("module_scope")).toBe("equipment");
        return HttpResponse.json(onePage(MIXED_LOCATIONS));
      }),
    );
  });

  it("lists locations without a context_tag alongside equipment ones", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Server Room")).toBeInTheDocument();
    });
    expect(screen.getByText("Biuro Kraków")).toBeInTheDocument();
  });

  it("highlights equipment-tagged locations with a badge", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Server Room")).toBeInTheDocument();
    });
    // One badge for the equipment location; the untagged one has none.
    expect(screen.getAllByText("Equipment")).toHaveLength(1);
  });

  it("introduces the empty screen instead of folding it into the title", async () => {
    server.use(
      http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
    );

    renderPage();

    const empty = await screen.findByTestId("empty-state");
    expect(
      within(empty).getByRole("heading", {
        level: 2,
        name: "No locations yet",
      }),
    ).toBeInTheDocument();
    expect(
      within(empty).getByText(
        "Add your first one so equipment has somewhere to stand.",
      ),
    ).toBeInTheDocument();
  });
});
