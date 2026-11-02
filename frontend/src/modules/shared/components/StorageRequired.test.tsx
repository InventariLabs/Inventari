import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { StorageRequired } from "./StorageRequired";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

/** Where the router stands — the settings action's target is the assertion. */
function LocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="location">{location.pathname + location.hash}</output>
  );
}

const renderComponent = (props = {}) => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <StorageRequired {...props} />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

/** The organization policy defaults to hiding module-owned locations. */
function mockStorages(all: unknown[], scoped: unknown[]) {
  server.use(
    http.get("/api/v1/organizations/my", () =>
      HttpResponse.json({ id: "org-1", name: "Org", settings: {} }),
    ),
    http.get("/api/v1/locations", ({ request }) => {
      const url = new URL(request.url);
      if (url.searchParams.get("exclude_module_contexts") === "true")
        return HttpResponse.json(onePage(scoped));
      return HttpResponse.json(onePage(all));
    }),
  );
}

describe("StorageRequired", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("creates the first storage without leaving the screen", async () => {
    const created: string[] = [];
    server.use(
      http.post("/api/v1/locations", async ({ request }) => {
        const body = (await request.json()) as { name: string };
        created.push(body.name);
        return HttpResponse.json(
          { id: "storage-1", name: body.name, parent_id: null },
          { status: 201 },
        );
      }),
    );
    const onCreated = vi.fn();
    renderComponent({ onCreated });

    await userEvent.click(
      screen.getByRole("button", { name: /create location/i }),
    );
    await userEvent.type(
      await screen.findByLabelText(/^name$/i),
      "Cold Storage",
    );
    await userEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(created).toEqual(["Cold Storage"]));
    expect(onCreated).toHaveBeenCalledWith(
      expect.objectContaining({ id: "storage-1" }),
    );
  });

  it("keeps the reader in place as a banner when the screen still works", () => {
    renderComponent({ variant: "banner" });

    expect(screen.getByText(/no locations yet/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /create location/i }),
    ).toBeInTheDocument();
  });

  it("names the hidden module data instead of offering a duplicate", async () => {
    // An organization that came from equipment_wms: the scoped answer is
    // empty while the flat list still holds the tagged locations. Offering
    // "create the first one" over two live locations is how duplicates are
    // born — the way back is the settings switch, and that is what the state
    // names.
    mockStorages(
      [{ id: "loc-eq", name: "IT Storage", context_tag: "equipment" }],
      [],
    );

    renderComponent();

    expect(
      await screen.findByText("Some locations are hidden"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /open settings/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /create location/i }),
    ).not.toBeInTheDocument();
  });

  it("says the same in the banner variant", async () => {
    mockStorages(
      [{ id: "loc-eq", name: "IT Storage", context_tag: "equipment" }],
      [],
    );

    renderComponent({ variant: "banner" });

    expect(
      await screen.findByText("Some locations are hidden"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /open settings/i }),
    ).toBeInTheDocument();
  });

  it("blames the module-data setting, not a switched-off module", async () => {
    // The organization behind this state came from equipment_wms: the module
    // is ON, its data is kept out of general lists by a setting. Sending the
    // reader hunting for a switched-off module that does not exist was the
    // defect.
    mockStorages(
      [{ id: "loc-eq", name: "IT Storage", context_tag: "equipment" }],
      [],
    );

    renderComponent();

    expect(
      await screen.findByText(/Module data in general lists/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/switched-off module/i)).not.toBeInTheDocument();
  });

  it("lands the settings action on the switch itself", async () => {
    mockStorages(
      [{ id: "loc-eq", name: "IT Storage", context_tag: "equipment" }],
      [],
    );
    renderComponent();

    await userEvent.click(
      await screen.findByRole("button", { name: /open settings/i }),
    );

    expect(screen.getByTestId("location")).toHaveTextContent(
      "/settings#module-data",
    );
  });

  it("as a field note under a picker, offers to create even when locations are hidden", async () => {
    // A form's task is to save a record: the field variant names the setting
    // but keeps the create action the screen and banner variants withhold.
    mockStorages(
      [{ id: "loc-eq", name: "IT Storage", context_tag: "equipment" }],
      [],
    );

    renderComponent({ variant: "field" });

    expect(
      await screen.findByText(
        /belong to a module and stay out of general lists/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /create location/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /open settings/i }),
    ).toBeInTheDocument();
  });

  it("as a field note with truly nowhere, leads with the create action", async () => {
    mockStorages([], []);

    renderComponent({ variant: "field" });

    expect(await screen.findByText(/no locations yet/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /create location/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /open settings/i }),
    ).not.toBeInTheDocument();
  });
});
