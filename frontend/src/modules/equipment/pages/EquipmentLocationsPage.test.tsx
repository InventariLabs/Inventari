import React, { useState } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";

import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { ModulesProvider } from "@/contexts/ModulesContext";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import { onePage } from "@/test/mocks/page";
import { queryKeys } from "@/hooks/queries/keys";

import EquipmentLocationsPage from "./EquipmentLocationsPage";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const base = {
  user_id: "u1",
  location_type_id: null,
  parent_id: null,
  location_details: null,
  settings: null,
  created_at: "2024-01-01T00:00:00Z",
  context_schema: [],
  behavior_mode: "NONE",
  field_definitions: [],
  context_tag: "equipment",
  items_count: 0,
};

const LOCATIONS = [
  {
    ...base,
    id: "loc-office",
    name: "Warsaw office",
    short_code: "WAW",
    description: null,
  },
  {
    ...base,
    id: "loc-server",
    name: "Server room",
    short_code: "SRV",
    description: "Second floor",
  },
];

beforeEach(() => {
  signInWith(["equipment:read", "locations:read", "locations:write"]);
  server.use(
    http.get("/api/v1/locations", () => HttpResponse.json(onePage(LOCATIONS))),
    http.get("/api/v1/locations/loc-server", () =>
      HttpResponse.json(LOCATIONS[1]),
    ),
  );
});

afterEach(() => {
  signOut();
});

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");

  function HeaderHost({ children }: { children: React.ReactNode }) {
    const [data, setData] = useState<PageHeaderData>({});
    return (
      <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
        {data.actions ? <div>{data.actions}</div> : null}
        {children}
      </PageHeaderContext.Provider>
    );
  }

  render(
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter>
          <HeaderHost>
            <EquipmentLocationsPage />
          </HeaderHost>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>,
  );
  return { invalidate, user: userEvent.setup() };
}

/**
 * The add form creates an equipment-tagged location in one hierarchy call;
 * the edit form saves name and description to the location's own address.
 * The failures caught: a location created without the module's tag (it
 * would vanish from this screen), an edit that loses the description the
 * detail call loaded, and forms that stay open over a saved record.
 */
describe("EquipmentLocationsPage — adding and editing", () => {
  it("creates a tagged location with the trimmed name and closes the form", async () => {
    let body: Record<string, unknown> = {};
    server.use(
      http.post("/api/v1/locations/hierarchy", async ({ request }) => {
        body = (await request.json()) as typeof body;
        return HttpResponse.json({ ...base, id: "loc-new", name: "Lab" });
      }),
    );
    const { user } = renderPage();
    await screen.findByText("Warsaw office");

    await user.click(screen.getByRole("button", { name: "Add Location" }));
    await user.type(screen.getByLabelText(/Location name/), "  Lab  ");
    await user.type(screen.getByLabelText("Description"), "Ground floor");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "Location created successfully",
      ),
    );
    expect(body).toMatchObject({
      steps: [{ name: "Lab" }],
      description: "Ground floor",
      context_tag: "equipment",
    });
    expect(body.parent_id).toBeUndefined();
    expect(screen.queryByLabelText(/Location name/)).not.toBeInTheDocument();
  });

  it("keeps Save off until there is a name, and Cancel closes the form unsaved", async () => {
    const created = vi.fn();
    server.use(
      http.post("/api/v1/locations/hierarchy", () => {
        created();
        return HttpResponse.json({});
      }),
    );
    const { user } = renderPage();
    await screen.findByText("Warsaw office");

    await user.click(screen.getByRole("button", { name: "Add Location" }));
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await user.type(screen.getByLabelText(/Location name/), "   ");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText(/Location name/)).not.toBeInTheDocument();
    expect(created).not.toHaveBeenCalled();
  });

  it("edits a location in place, starting from the description it already has", async () => {
    let body: Record<string, unknown> = {};
    server.use(
      http.put("/api/v1/locations/loc-server", async ({ request }) => {
        body = (await request.json()) as typeof body;
        return HttpResponse.json({ ...LOCATIONS[1], ...body });
      }),
    );
    const { user, invalidate } = renderPage();
    await screen.findByText("Server room");

    await user.click(screen.getByRole("button", { name: "Edit Server room" }));
    const description = await screen.findByDisplayValue("Second floor");
    const name = screen.getByDisplayValue("Server room");
    await user.clear(name);
    await user.type(name, "Server room B");
    await user.clear(description);
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Location updated"),
    );
    expect(body).toEqual({ name: "Server room B", description: null });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: queryKeys.storages.all,
    });
    expect(screen.queryByDisplayValue("Server room B")).not.toBeInTheDocument();
  });

  it("drops an edit on Cancel", async () => {
    const saved = vi.fn();
    server.use(
      http.put("/api/v1/locations/loc-server", () => {
        saved();
        return HttpResponse.json(LOCATIONS[1]);
      }),
    );
    const { user } = renderPage();
    await screen.findByText("Server room");

    await user.click(screen.getByRole("button", { name: "Edit Server room" }));
    await screen.findByDisplayValue("Second floor");
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByDisplayValue("Second floor")).not.toBeInTheDocument();
    expect(saved).not.toHaveBeenCalled();
  });
});

describe("EquipmentLocationsPage — finding and deleting", () => {
  // The search is the server's: the page sends what was typed and lists the
  // page that comes back, so a place past the first page is still findable.
  it("asks the server for what was typed and says when nothing matches", async () => {
    const asked: string[] = [];
    server.use(
      http.get("/api/v1/locations", ({ request }) => {
        const needle = (
          new URL(request.url).searchParams.get("q") ?? ""
        ).toLowerCase();
        if (needle) asked.push(needle);
        return HttpResponse.json(
          onePage(
            LOCATIONS.filter((loc) =>
              [loc.name, loc.short_code].some((field) =>
                field.toLowerCase().includes(needle),
              ),
            ),
          ),
        );
      }),
    );
    const { user } = renderPage();
    await screen.findByText("Warsaw office");

    const search = screen.getByPlaceholderText("Search locations…");
    await user.type(search, "srv");
    await waitFor(() =>
      expect(screen.queryByText("Warsaw office")).not.toBeInTheDocument(),
    );
    expect(screen.getByText("Server room")).toBeInTheDocument();
    expect(asked.at(-1)).toBe("srv");

    await user.clear(search);
    await user.type(search, "basement");
    expect(
      await screen.findByText("No locations match your search"),
    ).toBeInTheDocument();
  });

  it("deletes an empty location after the confirmation", async () => {
    const deleted = vi.fn();
    server.use(
      http.delete("/api/v1/locations/loc-office", () => {
        deleted();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const { user } = renderPage();
    await screen.findByText("Warsaw office");

    await user.click(
      screen.getByRole("button", { name: "Delete Warsaw office" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    expect(
      within(dialog).getByText('Delete location "Warsaw office"?'),
    ).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Location deleted"),
    );
    expect(deleted).toHaveBeenCalledTimes(1);
  });

  it("sends nothing when the delete is cancelled", async () => {
    const deleted = vi.fn();
    server.use(
      http.delete("/api/v1/locations/loc-office", () => {
        deleted();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const { user } = renderPage();
    await screen.findByText("Warsaw office");

    await user.click(
      screen.getByRole("button", { name: "Delete Warsaw office" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(deleted).not.toHaveBeenCalled();
  });
});
