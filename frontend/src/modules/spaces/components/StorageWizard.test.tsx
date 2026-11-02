import React from "react";
import {
  act,
  render,
  screen,
  fireEvent,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import StorageWizard from "./StorageWizard";
import { makeStorageSummary } from "@/test/factories/storage";
import { serveLocations } from "@/test/serveLocations";
import type { StorageLocationSummary } from "@/types";
import { toast } from "sonner";
import { AxiosError, type AxiosResponse } from "axios";

const createHierarchyMutate = vi.fn();

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

/** What the wizard's type picker is handed; empty unless a test sets it. */
const typeQuery = vi.hoisted(() => ({
  data: [] as Array<Record<string, unknown>>,
  error: null as unknown,
  refetch: vi.fn(),
}));

/** Garage → Rack → Shelf: the third level ADR-014 could not go past. */
const deepChain: StorageLocationSummary[] = [
  makeStorageSummary({ id: "garage", name: "Garage", full_path: "Garage" }),
  makeStorageSummary({
    id: "rack",
    name: "Rack",
    parent_id: "garage",
    full_path: "Garage → Rack",
  }),
  makeStorageSummary({
    id: "shelf",
    name: "Shelf",
    parent_id: "rack",
    full_path: "Garage → Rack → Shelf",
  }),
];

const serve = (rows: StorageLocationSummary[]) => serveLocations(rows);

vi.mock("@/modules/shared/hooks/useStorages", () => ({
  useStorageTypes: () => ({
    data: typeQuery.data,
    error: typeQuery.error,
    refetch: typeQuery.refetch,
  }),
}));

vi.mock("@/modules/shared/hooks/useStorageMutations", () => ({
  useCreateStorageHierarchy: () => ({
    mutate: createHierarchyMutate,
    isPending: false,
  }),
}));

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{children}</BrowserRouter>
    </QueryClientProvider>
  );
};

describe("StorageWizard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    serve([]);
  });

  it("renders nothing when isOpen is false", () => {
    const { container } = render(
      <StorageWizard isOpen={false} onClose={vi.fn()} />,
      { wrapper: createWrapper() },
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders wizard when isOpen is true", async () => {
    render(<StorageWizard isOpen={true} onClose={vi.fn()} />, {
      wrapper: createWrapper(),
    });
    await waitFor(() => {
      // Wizard renders a full-screen fixed overlay — the Next/Create button must be visible
      const buttons = screen.getAllByRole("button");
      expect(buttons.length).toBeGreaterThan(0);
    });
  });

  it("step 1 shows zone input", async () => {
    render(<StorageWizard isOpen={true} onClose={vi.fn()} />, {
      wrapper: createWrapper(),
    });
    await waitFor(() => {
      // step 1: zone name input is present
      const inputs = screen.getAllByRole("textbox");
      expect(inputs.length).toBeGreaterThan(0);
    });
  });

  it("finishes on the zone alone, without inventing a shelf", async () => {
    // Done used to stay disabled until a location name appeared — a place
    // wanting one place had to invent a second one inside it.
    render(<StorageWizard isOpen={true} onClose={vi.fn()} />, {
      wrapper: createWrapper(),
    });
    const zoneInput = await screen.findByRole("textbox");
    fireEvent.change(zoneInput, { target: { value: "Workshop" } });

    // Step 1 -> Next; step 2 offers Done without a location name.
    fireEvent.click(await screen.findByRole("button", { name: "Next" }));
    const done = await screen.findByRole("button", { name: "Done" });
    expect(done).not.toBeDisabled();
    fireEvent.click(done);

    // ADR-018: finishing on the first location is a one-step chain, not a
    // chain with a null leaf name.
    expect(createHierarchyMutate).toHaveBeenCalledWith(
      expect.objectContaining({ steps: [{ name: "Workshop" }] }),
      expect.anything(),
    );
  });

  // ADR-018: step 1 used to offer a chip per child-of-a-root, so a shelf
  // three levels down could not be built on — the wizard could only ever add
  // to the second level.
  it("offers a location three levels down as the parent", async () => {
    const user = userEvent.setup();
    serve(deepChain);
    render(<StorageWizard isOpen={true} onClose={vi.fn()} />, {
      wrapper: createWrapper(),
    });

    await user.click(
      await screen.findByRole("combobox", { name: /existing location/i }),
    );

    expect(await screen.findByText("Shelf")).toBeInTheDocument();
    // The path is what tells two shelves called "Top" apart.
    expect(screen.getByText("Garage › Rack")).toBeInTheDocument();
  });

  it("hangs the new location under the parent that was picked", async () => {
    const user = userEvent.setup();
    serve(deepChain);
    render(<StorageWizard isOpen={true} onClose={vi.fn()} />, {
      wrapper: createWrapper(),
    });

    await user.click(
      await screen.findByRole("combobox", { name: /existing location/i }),
    );
    await user.click(await screen.findByText("Shelf"));

    fireEvent.change(await screen.findByRole("textbox"), {
      target: { value: "Box 4" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));

    expect(createHierarchyMutate).toHaveBeenCalledWith(
      expect.objectContaining({ steps: [{ id: "shelf" }, { name: "Box 4" }] }),
      expect.anything(),
    );
  });

  it("will not report a creation when nothing would be created", async () => {
    const user = userEvent.setup();
    serve(deepChain);
    render(<StorageWizard isOpen={true} onClose={vi.fn()} />, {
      wrapper: createWrapper(),
    });

    await user.click(
      await screen.findByRole("combobox", { name: /existing location/i }),
    );
    await user.click(await screen.findByText("Shelf"));

    // A chain whose only step is a location that already exists hands back
    // that location and says "created".
    expect(await screen.findByRole("button", { name: "Done" })).toBeDisabled();
  });

  it("calls onClose when close button clicked", async () => {
    const onClose = vi.fn();
    render(<StorageWizard isOpen={true} onClose={onClose} />, {
      wrapper: createWrapper(),
    });
    // The first-run sheet is portaled to the body — the fullscreen panel is
    // the viewport, not a child of whatever page rendered it — so the query
    // goes through the screen, not the render container.
    fireEvent.click(await screen.findByRole("button", { name: "Close" }));

    expect(onClose).toHaveBeenCalled();
  });
});

/**
 * Leaving the wizard.
 *
 * This sheet was the one dialog in the app that ignored Escape: the key moved
 * focus to the cross, the ring appeared on it, and the wizard stayed open. The
 * answer is not "close on Escape" on its own — the wizard holds three steps,
 * and a name typed in the second one is not less of a draft than a recipe.
 * Every exit goes through one guard: an empty step leaves at once, a step with
 * something in it asks first.
 */
describe("StorageWizard - leaving a step", () => {
  const DISCARD_TITLE = "Discard this new location?";
  const DISCARD_MESSAGE =
    "The names and tracking fields you chose will be lost.";
  const DISCARD_CONFIRM = "Discard";
  const DISCARD_CANCEL = "Keep editing";

  const renderWizard = (onClose: () => void) =>
    render(<StorageWizard isOpen onClose={onClose} />, {
      wrapper: createWrapper(),
    });

  const clickBackdrop = () => {
    const backdrop = screen.getByRole("dialog").parentElement as HTMLElement;
    fireEvent.mouseDown(backdrop);
    fireEvent.click(backdrop);
  };

  const closeButton = () => screen.getByRole("button", { name: "Close" });

  const typeIntoFirstStep = async (value: string) => {
    const input = await screen.findByRole("textbox");
    fireEvent.change(input, { target: { value } });
    return input as HTMLInputElement;
  };

  describe("first run - the sheet fills the screen", () => {
    it("closes an empty step on Escape, without asking", async () => {
      const onClose = vi.fn();
      renderWizard(onClose);
      await screen.findByRole("textbox");

      fireEvent.keyDown(document, { key: "Escape" });

      expect(screen.queryByText(DISCARD_TITLE)).not.toBeInTheDocument();
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it("asks before Escape throws away a name", async () => {
      const onClose = vi.fn();
      renderWizard(onClose);
      await typeIntoFirstStep("Workshop");

      fireEvent.keyDown(document, { key: "Escape" });

      expect(onClose).not.toHaveBeenCalled();
      expect(screen.getByText(DISCARD_TITLE)).toBeInTheDocument();
      expect(screen.getByText(DISCARD_MESSAGE)).toBeInTheDocument();
    });

    it("keeps the wizard, and the name, when the question is refused", async () => {
      const onClose = vi.fn();
      renderWizard(onClose);
      const input = await typeIntoFirstStep("Workshop");

      fireEvent.click(closeButton());
      fireEvent.click(screen.getByRole("button", { name: DISCARD_CANCEL }));

      expect(screen.queryByText(DISCARD_TITLE)).not.toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();
      expect(input).toHaveValue("Workshop");
    });

    it("closes when the question is answered", async () => {
      const onClose = vi.fn();
      renderWizard(onClose);
      await typeIntoFirstStep("Workshop");

      fireEvent.click(closeButton());
      fireEvent.click(screen.getByRole("button", { name: DISCARD_CONFIRM }));

      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it("asks before the cross throws away a name", async () => {
      const onClose = vi.fn();
      renderWizard(onClose);
      await typeIntoFirstStep("Workshop");

      fireEvent.click(closeButton());

      expect(onClose).not.toHaveBeenCalled();
      expect(screen.getByText(DISCARD_TITLE)).toBeInTheDocument();
    });

    it("closes from the cross without asking when nothing was typed", async () => {
      const onClose = vi.fn();
      renderWizard(onClose);
      await screen.findByRole("textbox");

      fireEvent.click(closeButton());

      expect(screen.queryByText(DISCARD_TITLE)).not.toBeInTheDocument();
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  describe("everyday run - the sheet sits over the page", () => {
    beforeEach(() => {
      serve(deepChain);
    });

    it("closes an empty step on Escape, without asking", async () => {
      const onClose = vi.fn();
      renderWizard(onClose);
      await screen.findByRole("textbox");

      fireEvent.keyDown(document, { key: "Escape" });

      expect(screen.queryByText(DISCARD_TITLE)).not.toBeInTheDocument();
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it("asks before Escape throws away a name", async () => {
      const onClose = vi.fn();
      renderWizard(onClose);
      await typeIntoFirstStep("Workshop");

      fireEvent.keyDown(document, { key: "Escape" });

      expect(onClose).not.toHaveBeenCalled();
      expect(screen.getByText(DISCARD_TITLE)).toBeInTheDocument();
    });

    it("asks before a click on the backdrop throws away a name", async () => {
      const onClose = vi.fn();
      renderWizard(onClose);
      await typeIntoFirstStep("Workshop");

      clickBackdrop();

      expect(onClose).not.toHaveBeenCalled();
      expect(screen.getByText(DISCARD_TITLE)).toBeInTheDocument();
    });

    it("closes from the backdrop without asking when nothing was typed", async () => {
      const onClose = vi.fn();
      renderWizard(onClose);
      await screen.findByRole("textbox");

      clickBackdrop();

      expect(screen.queryByText(DISCARD_TITLE)).not.toBeInTheDocument();
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it("leaves Escape to the question once it is up", async () => {
      // Both layers listen on `document`; the press that answers the question
      // must not travel down and throw the wizard away with it.
      const onClose = vi.fn();
      renderWizard(onClose);
      await typeIntoFirstStep("Workshop");
      fireEvent.click(closeButton());

      fireEvent.keyDown(document, { key: "Escape" });

      expect(onClose).not.toHaveBeenCalled();
      expect(screen.queryByText(DISCARD_TITLE)).not.toBeInTheDocument();
      expect(screen.getByRole("textbox")).toHaveValue("Workshop");
    });

    it("asks again on the next Escape", async () => {
      const onClose = vi.fn();
      renderWizard(onClose);
      await typeIntoFirstStep("Workshop");
      fireEvent.click(closeButton());
      fireEvent.keyDown(document, { key: "Escape" });

      fireEvent.keyDown(document, { key: "Escape" });

      expect(screen.getByText(DISCARD_TITLE)).toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();
    });

    it("closes only the location list on Escape, keeping the step and the name", async () => {
      // The wizard's first control opens a list that is itself a sheet on a
      // phone. One press used to close the list *and* raise the discard
      // question over it — three layers, and a destructive "Discard" a click
      // away. Escape belongs to the highest layer only.
      const onClose = vi.fn();
      renderWizard(onClose);
      await typeIntoFirstStep("Workshop");
      fireEvent.click(
        screen.getByRole("combobox", { name: /existing location/i }),
      );
      expect(screen.getAllByRole("dialog")).toHaveLength(2);

      fireEvent.keyDown(document, { key: "Escape" });

      expect(screen.getAllByRole("dialog")).toHaveLength(1);
      expect(screen.queryByText(DISCARD_TITLE)).not.toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();
      expect(screen.getByRole("textbox")).toHaveValue("Workshop");

      // The next press is the wizard's own: a step with a name asks first.
      fireEvent.keyDown(document, { key: "Escape" });
      expect(screen.getByText(DISCARD_TITLE)).toBeInTheDocument();
    });
  });

  describe("the dialog belongs to the sheet", () => {
    // The two shapes the wizard wears: the first run is the surface the
    // fullscreen layer is for, every other visit is a bottom sheet.
    const shapes = [
      {
        name: "first run",
        rows: [] as StorageLocationSummary[],
        panel: "h-full",
      },
      { name: "everyday run", rows: deepChain, panel: "rounded-t-3xl" },
    ];

    it.each(shapes)(
      "hands the layer to the shared overlay ($name)",
      async ({ rows, panel }) => {
        serve(rows);
        renderWizard(vi.fn());

        const dialog = await screen.findByRole("dialog", {
          name: "Location Wizard",
        });

        // The panel is the sheet's content - the geometry and the layer are
        // the overlay's, not a second dialog shell written here. Which shape
        // it wears is decided once the organization's locations have been
        // counted.
        await waitFor(() =>
          expect(
            screen.getByRole("dialog", { name: "Location Wizard" }).className,
          ).toContain(panel),
        );
        expect(dialog.className).toContain("overflow-hidden");
        expect(dialog.className).not.toContain("z-[var(--z-fullscreen)]");
        expect(dialog.parentElement?.style.zIndex).toBe("var(--z-fullscreen)");
      },
    );
  });
});

// Step 2's chips follow where the new row will stand: inside an appliance
// or under anything that is not a root they name compartments — shelves,
// drawers, bins — while a root, or a zone the first step just typed, gets
// the places themselves. Before this, one list per profile served every
// parent, so "+" under a "Freezer Zone" offered a "Fridge" and a second
// "Freezer".
describe("StorageWizard - step 2 suggestions follow the parent", () => {
  const applianceType = (type_code: string) => ({
    id: `type-${type_code}`,
    name: type_code,
    type_code,
    behavior_mode: "STOCK" as const,
    icon: null,
    default_settings: null,
    context_schema: null,
    organization_id: null,
    is_system: false,
    field_definitions: [],
  });

  it("offers compartments inside a freezer, not appliances", async () => {
    serve([
      makeStorageSummary({
        id: "freezer-zone",
        name: "Freezer Zone",
        parent_id: null,
        full_path: "Freezer Zone",
        location_type: applianceType("FREEZER"),
      }),
    ]);
    render(
      <StorageWizard
        isOpen={true}
        onClose={vi.fn()}
        preselectedParentId="freezer-zone"
      />,
      { wrapper: createWrapper() },
    );
    // Step 2 opens straight away with a preselected parent.
    expect(
      await screen.findByRole("button", { name: "Shelf" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Drawer" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Fridge" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Freezer" })).toBeNull();
  });

  it("offers the places themselves under a root", async () => {
    serve([
      makeStorageSummary({
        id: "home",
        name: "Home",
        parent_id: null,
        full_path: "Home",
      }),
    ]);
    render(
      <StorageWizard
        isOpen={true}
        onClose={vi.fn()}
        preselectedParentId="home"
      />,
      { wrapper: createWrapper() },
    );
    // A root holds places — appliances and furniture — not their drawers.
    expect(
      await screen.findByRole("button", { name: "Fridge" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Drawer" })).toBeNull();
  });

  it("offers compartments under a non-root of a plain type", async () => {
    serve([
      makeStorageSummary({
        id: "home",
        name: "Home",
        parent_id: null,
        full_path: "Home",
      }),
      makeStorageSummary({
        id: "storage-room",
        name: "Storage room",
        parent_id: "home",
        full_path: "Home → Storage room",
        location_type: applianceType("STORAGE_ROOM"),
      }),
    ]);
    render(
      <StorageWizard
        isOpen={true}
        onClose={vi.fn()}
        preselectedParentId="storage-room"
      />,
      { wrapper: createWrapper() },
    );
    expect(
      await screen.findByRole("button", { name: "Drawer" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Fridge" })).toBeNull();
  });

  it("does not offer a name a sibling already carries", async () => {
    serve([
      makeStorageSummary({
        id: "freezer-zone",
        name: "Freezer Zone",
        parent_id: null,
        full_path: "Freezer Zone",
        location_type: applianceType("FREEZER"),
      }),
      makeStorageSummary({
        id: "shelf-1",
        name: "Shelf",
        parent_id: "freezer-zone",
        full_path: "Freezer Zone → Shelf",
      }),
    ]);
    render(
      <StorageWizard
        isOpen={true}
        onClose={vi.fn()}
        preselectedParentId="freezer-zone"
      />,
      { wrapper: createWrapper() },
    );
    // "Shelf" is taken by a sibling; "Drawer" is not.
    expect(
      await screen.findByRole("button", { name: "Drawer" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Shelf" })).toBeNull(),
    );
  });
});

/**
 * The way through the three steps, and what the wizard hands the server when
 * it is finished. The create call is a stand-in, so each test answers it the
 * way the server would and watches what the wizard does with the answer.
 */
describe("StorageWizard - building a location through all three steps", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    typeQuery.data = [];
    typeQuery.error = null;
    serve([]);
  });

  /**
   * Opens the wizard and waits for its layout to settle. The sheet turns
   * full-screen once it knows the organization has no locations; a chip
   * pressed before that is pressed on a button the layout change replaces.
   */
  const openWizard = async (onClose: () => void = vi.fn()) => {
    const user = userEvent.setup();
    render(<StorageWizard isOpen onClose={onClose} />, {
      wrapper: createWrapper(),
    });
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: /Where do you keep/ }),
      ).not.toBeInTheDocument(),
    );
    await screen.findByText(/Where do you keep your things\?/);
    return user;
  };

  const lastCall = () =>
    createHierarchyMutate.mock.calls[
      createHierarchyMutate.mock.calls.length - 1
    ] as [
      Record<string, unknown>,
      { onSuccess: () => void; onError: (error: unknown) => void },
    ];

  it("takes a suggested zone and a suggested place, and creates exactly that chain", async () => {
    const user = await openWizard();

    await user.click(await screen.findByRole("button", { name: "Pantry" }));
    // Pressing a zone chip moves on to naming the place inside it.
    await user.click(await screen.findByRole("button", { name: "Fridge" }));
    await user.click(screen.getByRole("button", { name: "Done" }));

    expect(lastCall()[0]).toMatchObject({
      steps: [{ name: "Pantry" }, { name: "Fridge" }],
    });
  });

  it("goes back from the second step to the first and forgets the place name typed there", async () => {
    const user = await openWizard();

    await user.click(await screen.findByRole("button", { name: "Pantry" }));
    await user.type(await screen.findByPlaceholderText(/e\.g\./i), "Top shelf");
    await user.click(screen.getByRole("button", { name: "Back" }));

    expect(
      await screen.findByRole("button", { name: "Garage" }),
    ).toBeInTheDocument();
    expect(createHierarchyMutate).not.toHaveBeenCalled();
  });

  it("sends the type, tracked fields, description and code chosen on the third step", async () => {
    typeQuery.data = [
      { id: "t-rack", name: "Rack", context_schema: ["price"] },
      { id: "t-bin", name: "Bin", context_schema: [] },
    ];
    const user = await openWizard();

    await user.click(await screen.findByRole("button", { name: "Garage" }));
    await user.click(await screen.findByRole("button", { name: "Fridge" }));
    await user.click(screen.getByRole("button", { name: /customize/i }));

    // A type seeds the tracked fields; one more is switched on by hand and
    // the seeded one is switched off again.
    await user.selectOptions(screen.getByLabelText("Location type"), "t-rack");
    await user.click(screen.getByRole("button", { name: /Notes/ }));
    await user.click(screen.getByRole("button", { name: /^Price/ }));
    // A type with no fields leaves the chosen ones as they are.
    await user.selectOptions(screen.getByLabelText("Location type"), "t-bin");

    await user.click(screen.getByRole("button", { name: /Advanced options/ }));
    await user.type(screen.getByLabelText("Description"), "Tools");
    await user.type(screen.getByLabelText("Label code"), "gar-1");
    await user.click(screen.getByRole("button", { name: "Done" }));

    expect(lastCall()[0]).toMatchObject({
      steps: [{ name: "Garage" }, { name: "Fridge" }],
      context_schema: ["notes"],
      location_type_id: "t-bin",
      description: "Tools",
      short_code: "GAR-1",
    });
  });

  it("walks back from the third step to the second", async () => {
    const user = await openWizard();

    await user.click(await screen.findByRole("button", { name: "Garage" }));
    await user.click(await screen.findByRole("button", { name: "Fridge" }));
    await user.click(screen.getByRole("button", { name: /customize/i }));
    expect(await screen.findByLabelText("Location type")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Back" }));

    expect(
      await screen.findByRole("button", { name: "Freezer" }),
    ).toBeInTheDocument();
  });

  it("announces the new location and closes the wizard once the server accepted the chain", async () => {
    const onClose = vi.fn();
    const user = await openWizard(onClose);

    await user.click(await screen.findByRole("button", { name: "Garage" }));
    await user.click(await screen.findByRole("button", { name: "Done" }));
    act(() => lastCall()[1].onSuccess());

    expect(toast.success).toHaveBeenCalledWith("Location added successfully!");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("keeps the wizard open and shows the server's reason when the chain is refused", async () => {
    const onClose = vi.fn();
    const user = await openWizard(onClose);

    await user.click(await screen.findByRole("button", { name: "Garage" }));
    await user.click(await screen.findByRole("button", { name: "Done" }));
    act(() =>
      lastCall()[1].onError(
        new AxiosError("conflict", "ERR_BAD_REQUEST", undefined, undefined, {
          status: 409,
          data: { detail: "Name already used" },
        } as AxiosResponse),
      ),
    );

    expect(toast.error).toHaveBeenCalledWith("Name already used");
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Done" })).toBeInTheDocument();
  });

  it("asks the types again when 'Try again' is pressed on the third step", async () => {
    typeQuery.error = new Error("down");
    const user = await openWizard();

    await user.click(await screen.findByRole("button", { name: "Garage" }));
    await user.click(await screen.findByRole("button", { name: "Fridge" }));
    await user.click(screen.getByRole("button", { name: /customize/i }));
    await user.click(await screen.findByRole("button", { name: "Try again" }));

    expect(typeQuery.refetch).toHaveBeenCalledTimes(1);
  });
});
