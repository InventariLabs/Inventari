/** A location that says "3 assets live here" has to lead to them.
 *
 * The row already showed the count and used the same count to refuse the
 * delete — information without a door. The name is now the door: a real
 * link to the asset list narrowed to this location, so mouse, keyboard and
 * screen reader all take the same path. A location holding nothing keeps a
 * plain name — no promise of a transition that ends in an unexplained
 * empty list.
 */

import React, { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
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

const LOCATIONS = [
  {
    id: "loc-1",
    user_id: "u1",
    location_type_id: null,
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
    items_count: 3,
    subtree_items_count: 3,
  },
  {
    id: "loc-2",
    user_id: "u1",
    location_type_id: null,
    parent_id: null,
    name: "Empty Shelf",
    description: null,
    location_details: null,
    settings: null,
    created_at: "2024-01-01T00:00:00Z",
    context_schema: [],
    behavior_mode: "NONE",
    field_definitions: [],
    context_tag: null,
    items_count: 0,
    subtree_items_count: 0,
  },
  {
    // The parent case: nothing stands HERE, the subtree holds plenty. The
    // asset list narrows on direct location, so a link keyed on the subtree
    // count promised a room the list could not show.
    id: "loc-3",
    user_id: "u1",
    location_type_id: null,
    parent_id: null,
    name: "Wide Campus",
    description: null,
    location_details: null,
    settings: null,
    created_at: "2024-01-01T00:00:00Z",
    context_schema: [],
    behavior_mode: "NONE",
    field_definitions: [],
    context_tag: "equipment",
    items_count: 0,
    subtree_items_count: 27,
  },
] as unknown as StorageLocation[];

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

describe("EquipmentLocationsPage — a holding location leads to its assets", () => {
  beforeEach(() => {
    server.resetHandlers();
    server.use(
      http.get("/api/v1/locations", () =>
        HttpResponse.json(onePage(LOCATIONS)),
      ),
    );
  });

  it("makes the name of a holding location a link to its assets", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Server Room")).toBeInTheDocument();
    });

    const link = screen.getByRole("link", { name: /Server Room/ });
    expect(link).toHaveAttribute("href", "/equipment/assets?location=loc-1");
  });

  it("keeps an empty location's name a plain promise-free word", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Empty Shelf")).toBeInTheDocument();
    });

    expect(
      screen.queryByRole("link", { name: /Empty Shelf/ }),
    ).not.toBeInTheDocument();
  });

  it("does not promise a list a parent with an empty here cannot back", async () => {
    // The subtree count reads 27, but the list narrows on what stands HERE
    // — following a link on that count landed the reader on an empty page
    // that contradicted the number they clicked.
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Wide Campus")).toBeInTheDocument();
    });

    expect(screen.getByText("Wide Campus").tagName).toBe("SPAN");
    expect(
      screen.queryByRole("link", { name: /Wide Campus/ }),
    ).not.toBeInTheDocument();
  });
});
