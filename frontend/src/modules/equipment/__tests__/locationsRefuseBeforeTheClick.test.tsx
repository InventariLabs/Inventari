import React, { useState } from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { signInWith, signOut } from "@/test/auth";
import { ModulesProvider } from "@/contexts/ModulesContext";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";

import EquipmentLocationsPage from "../pages/EquipmentLocationsPage";
import type { StorageLocationSummary } from "@/types";
import { onePage } from "@/test/mocks/page";
// The fixtures carry the counts the list endpoint computes (StorageLocationSummary) and
// an older base of identifiers; the cast keeps them as the test has always held them.

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

// The row actions are behind `locations:write`; without it there is no Delete
// button to be refused by, and the test would pass for the wrong reason.
beforeEach(() => {
  signInWith(["equipment:read", "locations:read", "locations:write"]);
});

afterEach(() => {
  signOut();
});

/**
 * Location is a required field of every record standing in one, so the API
 * refuses to delete a location that holds anything. The screen used to ask
 * for confirmation anyway and report a bare "Failed to delete" afterwards —
 * a question whose only possible answer was a refusal, phrased as a mishap.
 */

const base = {
  user_id: "u1",
  location_type_id: null,
  parent_id: null,
  description: null,
  location_details: null,
  settings: null,
  created_at: "2024-01-01T00:00:00Z",
  context_schema: [],
  behavior_mode: "NONE",
  field_definitions: [],
};

const LOCATIONS = [
  {
    ...base,
    id: "loc-empty",
    name: "Server Room",
    context_tag: "equipment",
    items_count: 0,
  },
  {
    ...base,
    id: "loc-held",
    name: "Desk 14",
    context_tag: null,
    items_count: 3,
  },
  // A parent holding nothing itself, with a subtree: the delete is a tree
  // rebuild, and the confirmation has to say so before the click.
  {
    ...base,
    id: "loc-office",
    name: "Office Building",
    context_tag: "equipment",
    items_count: 0,
    total_subtree_items_count: 4,
    direct_children_count: 1,
  },
  {
    ...base,
    id: "loc-work",
    name: "Workstations",
    parent_id: "loc-office",
    context_tag: "equipment",
    items_count: 4,
  },
] as unknown as StorageLocationSummary[];

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

describe("deleting a location that holds something", () => {
  beforeEach(() => {
    server.resetHandlers();
    server.use(
      // The search is the server's: name, path or short code contains `q`.
      http.get("/api/v1/locations", ({ request }) => {
        const q = new URL(request.url).searchParams.get("q")?.toLowerCase();
        return HttpResponse.json(
          onePage(
            LOCATIONS.filter((loc) => !q || loc.name.toLowerCase().includes(q)),
          ),
        );
      }),
    );
  });

  it("refuses before the click, and says how many records are in the way", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Desk 14")).toBeInTheDocument();
    });

    const refused = screen.getByRole("button", {
      name: /Cannot delete: 3 records/,
    });

    expect(refused).toBeDisabled();
  });

  it("leaves the empty one deletable", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Server Room")).toBeInTheDocument();
    });

    // Three rows, one Delete each; the enabled ones belong to the empty
    // locations (Server Room, and the Office Building that holds nothing
    // directly but carries a subtree). Asserting on the count as well, so a
    // change that disables everything does not read as a pass.
    const enabled = screen
      .getAllByRole("button", { name: /^Delete / })
      .filter((button) => !button.hasAttribute("disabled"));

    expect(enabled).toHaveLength(2);
  });

  it("names what the tree loses before a parent's delete is confirmed", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Office Building")).toBeInTheDocument();
    });

    // Empty itself, so the button is live — but two child locations move
    // up a level and four records standing below move up with them.
    fireEvent.click(
      screen.getByRole("button", { name: "Delete Office Building" }),
    );

    expect(
      screen.getByText(/1 child location moves up a level/),
    ).toBeInTheDocument();
    expect(screen.getByText(/4 records move up a level/)).toBeInTheDocument();
  });

  it("uses the server's own counts: the child it never listed still moves", async () => {
    // The shape that broke the client-side fold: a second child the module
    // filter drops, and a grandchild below it. The listing carries two rows;
    // the tree behind them has three locations. The sentence says the
    // CHILDREN move up one level, so its number is the direct children —
    // including the one the list never showed — while the records count the
    // whole subtree. Both travel on the parent's row, counted by the server.
    server.use(
      http.get("/api/v1/locations", () =>
        HttpResponse.json(
          onePage([
            {
              ...base,
              id: "loc-hq",
              name: "Head Office",
              context_tag: "equipment",
              items_count: 0,
              total_subtree_items_count: 4,
              direct_children_count: 2,
            },
            {
              ...base,
              id: "loc-work",
              name: "Workstations",
              parent_id: "loc-hq",
              context_tag: "equipment",
              items_count: 4,
            },
            // Not in a module's own payload: a food-tagged child and, under
            // it, a grandchild. A fold over the rows above counts one child.
          ]),
        ),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Head Office")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Delete Head Office" }));

    expect(
      screen.getByText(/2 child locations move up a level/),
    ).toBeInTheDocument();
    expect(screen.getByText(/4 records move up a level/)).toBeInTheDocument();
  });

  it("narrows the list by name, path or code", async () => {
    // Thirty-odd rows and no way through them: "Shelf 3" is unfindable, and
    // the path is what actually tells them apart.
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Desk 14")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText("Search locations…"), {
      target: { value: "server" },
    });

    await waitFor(() => expect(screen.queryByText("Desk 14")).toBeNull());
    expect(screen.getByText("Server Room")).toBeInTheDocument();
  });

  it("says so when the search matches nothing", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Desk 14")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText("Search locations…"), {
      target: { value: "nothing here" },
    });

    // Not the empty state: there are locations, this search found none of
    // them, and the two say different things.
    expect(
      await screen.findByText("No locations match your search"),
    ).toBeInTheDocument();
  });

  it("says on the row what is standing there", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Desk 14")).toBeInTheDocument();
    });

    // A disabled button with the reason in a tooltip still leaves the reader
    // guessing what is in there. The count speaks for what this screen
    // lists — and the row calls it by the name the delete conversation
    // uses, not by a private second noun.
    expect(screen.getByText("3 records here")).toBeInTheDocument();
  });
});

describe("the count on a scoped row", () => {
  // A mixed building: two of this module's assets stand here, and so do
  // three records the module has no answer for. The row shows both truths —
  // its own count as the headline, the all-modules direct total as what the
  // delete button refuses on.
  const MIXED = [
    {
      ...base,
      id: "loc-mixed",
      name: "Office Building",
      context_tag: null,
      items_count: 2,
      subtree_items_count: 2,
      total_items_count: 5,
    },
    {
      ...base,
      id: "loc-parent",
      name: "Campus",
      context_tag: "equipment",
      items_count: 1,
      subtree_items_count: 3,
      total_items_count: 1,
    },
  ] as unknown as StorageLocationSummary[];

  beforeEach(() => {
    server.resetHandlers();
    server.use(
      http.get("/api/v1/locations", () => HttpResponse.json(onePage(MIXED))),
    );
  });

  it("names here and subtree apart where the two differ", async () => {
    // A parent row is where the two numbers drift apart; one bare count
    // cannot say which of the two questions it answers.
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Campus")).toBeInTheDocument();
    });

    expect(screen.getByText("1 here · 3 in the subtree")).toBeInTheDocument();
  });

  it("keeps the all-modules total visible when other modules stand here", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Office Building")).toBeInTheDocument();
    });

    expect(screen.getByText("5 records here in total")).toBeInTheDocument();
  });

  it("refuses the delete on the total, not on the narrowed count", async () => {
    // The narrowed count reads 2 — the server still refuses, because three
    // other records stand here too. The refusal cites the number the row
    // displays.
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Office Building")).toBeInTheDocument();
    });

    const refused = screen.getByRole("button", {
      name: /Cannot delete: 5 records/,
    });

    expect(refused).toBeDisabled();
  });
});
