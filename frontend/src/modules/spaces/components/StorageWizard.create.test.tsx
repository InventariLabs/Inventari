import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { serveLocations } from "@/test/serveLocations";
import { makeStorageSummary } from "@/test/factories/storage";
import StorageWizard from "./StorageWizard";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

let sent: Record<string, unknown> | null;

beforeEach(() => {
  sent = null;
  // A location with one inside it: not the first run, so the sheet keeps
  // one layout instead of switching to the full-screen one (and remounting
  // its fields) when the list arrives.
  serveLocations([
    makeStorageSummary({ id: "wh", name: "Warehouse" }),
    makeStorageSummary({ id: "bay", name: "Bay 1", parent_id: "wh" }),
  ]);
  server.use(
    http.get("/api/v1/location-types", () =>
      HttpResponse.json(
        onePage([
          {
            id: "type-fridge",
            name: "Fridge",
            type_code: "FRIDGE",
            behavior_mode: "EXPIRY",
            context_schema: ["expiry_date", "quantity"],
          },
        ]),
      ),
    ),
    http.post("/api/v1/locations/hierarchy", async ({ request }) => {
      sent = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({ id: "new", name: "x" }, { status: 201 });
    }),
  );
});

function renderWizard(onClose = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <StorageWizard isOpen onClose={onClose} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return onClose;
}

/** The parent picker appears once the list has arrived. */
const settled = () =>
  screen.findByRole("combobox", { name: /existing location/i });

/**
 * The wizard's whole output is one request. These walk the reader's paths
 * through the three steps and read that request: a suggestion chip that
 * does not land in the chain, a type whose fields are not applied, an
 * advanced field lost on the way, or a failure that closes the wizard over
 * the reader's typing — each fails one of them.
 */
describe("StorageWizard — what Done creates", () => {
  it("builds the chain from two suggestion chips and closes on success", async () => {
    const user = userEvent.setup();
    const onClose = renderWizard();

    await settled();
    fireEvent.click(await screen.findByRole("button", { name: "Kitchen" }));
    fireEvent.click(await screen.findByRole("button", { name: "Fridge" }));
    await user.click(screen.getByRole("button", { name: "Done" }));

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(sent?.steps).toEqual([{ name: "Kitchen" }, { name: "Fridge" }]);
    expect(toast.success).toHaveBeenCalledWith("Location added successfully!");
  });

  it("carries the type, its fields, the label code and the description from the third step", async () => {
    const user = userEvent.setup();
    renderWizard();

    await settled();
    await user.type(
      await screen.findByRole("textbox", { name: "Type or select" }),
      "Garage",
    );
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.type(
      await screen.findByRole("textbox", {
        name: "e.g. Shelf A, Bay 3, Cabinet 1",
      }),
      "Chest freezer",
    );
    await user.click(screen.getByRole("button", { name: "customize →" }));

    await user.selectOptions(
      await screen.findByLabelText("Location type"),
      "type-fridge",
    );
    await user.click(screen.getByRole("button", { name: "Advanced options" }));
    await user.type(screen.getByLabelText("Label code"), "gar-01");
    await user.type(screen.getByLabelText("Description"), "Left wall");
    await user.click(screen.getByRole("button", { name: "Done" }));

    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent).toMatchObject({
      steps: [{ name: "Garage" }, { name: "Chest freezer" }],
      location_type_id: "type-fridge",
      context_schema: ["expiry_date", "quantity"],
      short_code: "GAR-01",
      description: "Left wall",
    });
  });

  it("keeps the wizard open and says why when the server refuses", async () => {
    server.use(
      http.post("/api/v1/locations/hierarchy", () =>
        HttpResponse.json(
          { detail: "A location with that name exists here" },
          { status: 409 },
        ),
      ),
    );
    const user = userEvent.setup();
    const onClose = renderWizard();

    await settled();
    fireEvent.click(await screen.findByRole("button", { name: "Kitchen" }));
    fireEvent.click(await screen.findByRole("button", { name: "Fridge" }));
    await user.click(screen.getByRole("button", { name: "Done" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "A location with that name exists here",
      ),
    );
    expect(onClose).not.toHaveBeenCalled();
  });

  it("goes back from the second step to the first without the name typed there", async () => {
    const user = userEvent.setup();
    renderWizard();

    await settled();
    fireEvent.click(await screen.findByRole("button", { name: "Kitchen" }));
    const second = await screen.findByRole("textbox", {
      name: "e.g. Shelf A, Bay 3, Cabinet 1",
    });
    await user.type(second, "Spice rack");
    await user.click(screen.getByRole("button", { name: "Back" }));

    expect(
      await screen.findByRole("textbox", { name: "Type or select" }),
    ).toHaveValue("Kitchen");
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(
      await screen.findByRole("textbox", {
        name: "e.g. Shelf A, Bay 3, Cabinet 1",
      }),
    ).toHaveValue("");
  });
});
