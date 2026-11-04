import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { onePage } from "@/test/mocks/page";
import { server } from "@/test/mocks/server";
import { QueryWrapper } from "@/test/queryWrapper";
import { serveLocations } from "@/test/serveLocations";
import userEvent from "@testing-library/user-event";
import { StorageArchiveDialog } from "./StorageArchiveDialog";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

// The rule catalogue belongs to the warehouse module, so the dialog asks for
// it only where that module is on. The tests render outside the shell's
// provider, which would otherwise answer "no modules at all".
const { enabledModulesMock } = vi.hoisted(() => ({
  enabledModulesMock: vi.fn<() => string[]>(() => ["warehouse"]),
}));
vi.mock("@/contexts/ModulesContext", () => ({
  useEnabledModulesOptional: () => enabledModulesMock(),
}));

// Main Warehouse › Cold Storage (zone-1, edited) › Fridge A; Shelf B standalone.
const FLOOR = [
  { id: "site-1", name: "Main Warehouse", parent_id: null, is_leaf: false },
  { id: "zone-1", name: "Cold Storage", parent_id: "site-1", is_leaf: false },
  { id: "loc-1", name: "Fridge A", parent_id: "zone-1" },
  { id: "loc-9", name: "Shelf B", parent_id: null },
];

const serveFloor = (rows: Array<(typeof FLOOR)[number]> = FLOOR) =>
  serveLocations(rows);

const mockSummary = (itemsCount: number, subtreeCount: number) =>
  server.use(
    http.get("*/api/v1/locations/:id/summary", ({ params }) =>
      HttpResponse.json({
        id: params.id,
        name: "Cold Storage",
        items_count: itemsCount,
        subtree_items_count: subtreeCount,
        children_count: 0,
      }),
    ),
    // The archive question also counts active putaway rules naming the
    // location; tests that do not care about them get an empty list.
    http.get("*/api/v1/warehouse/putaway-rules", () =>
      HttpResponse.json(onePage([])),
    ),
  );

const mockPutawayRules = (
  rules: Array<{
    id: string;
    is_active: boolean;
    target_location_id: string;
    // The wire shape a rule really has: an ordered list of shelves, of which
    // `target_location_id` is only the first. Fixtures that carried the head
    // alone let the dialog count by the head alone and call itself proven.
    locations?: Array<{ location_id: string; position: number }>;
  }>,
) =>
  server.use(
    http.get("*/api/v1/warehouse/putaway-rules", () =>
      HttpResponse.json(onePage(rules)),
    ),
  );

const renderDialog = (
  rows?: Array<(typeof FLOOR)[number]>,
  subLocations?: number,
) => {
  const requests = serveFloor(rows);
  const onOpenChange = vi.fn();
  const onArchived = vi.fn();
  render(
    <QueryWrapper>
      <StorageArchiveDialog
        open
        storageId="zone-1"
        subLocations={subLocations}
        onOpenChange={onOpenChange}
        onArchived={onArchived}
      />
    </QueryWrapper>,
  );
  return { onOpenChange, onArchived, requests };
};

const confirmButton = () => screen.getByRole("button", { name: "Archive" });

describe("StorageArchiveDialog — sub-locations", () => {
  it("says the locations inside stay in the lists, at the top level", async () => {
    mockSummary(0, 0);
    renderDialog(undefined, 2);

    expect(
      await screen.findByText(
        /The 2 locations inside it are not archived with it/,
      ),
    ).toBeInTheDocument();
  });

  it("says nothing about sub-locations when there are none", async () => {
    mockSummary(0, 0);
    renderDialog(undefined, 0);

    await screen.findByText(/This will hide the location/);
    expect(screen.queryByText(/not archived with it/)).not.toBeInTheDocument();
  });
});

describe("StorageArchiveDialog — putaway rules warning", () => {
  it("names the count of active rules pointing at the location", async () => {
    mockSummary(0, 0);
    // One active rule on the location itself, one on a descendant shelf
    // (hidden together with it), one outside the subtree, one inactive —
    // the last two do not count.
    mockPutawayRules([
      { id: "r1", is_active: true, target_location_id: "zone-1" },
      { id: "r2", is_active: true, target_location_id: "loc-1" },
      { id: "r3", is_active: true, target_location_id: "loc-9" },
      { id: "r4", is_active: false, target_location_id: "zone-1" },
    ]);
    renderDialog();

    expect(
      await screen.findByText(/2 putaway rules point here/),
    ).toBeInTheDocument();
  });

  it("says nothing of the rules when the places inside could not be read", async () => {
    mockSummary(0, 0);
    mockPutawayRules([
      { id: "r1", is_active: true, target_location_id: "zone-1" },
      { id: "r2", is_active: true, target_location_id: "loc-1" },
    ]);
    renderDialog();
    const treeAsked = vi.fn();
    server.use(
      http.get("*/api/v1/locations/tree", () => {
        treeAsked();
        return HttpResponse.json({ detail: "down" }, { status: 500 });
      }),
    );

    await waitFor(() => expect(treeAsked).toHaveBeenCalled());
    await waitFor(() => expect(confirmButton()).toBeEnabled());
    // Let the rules arrive: counted without the places inside, they would
    // read "1 putaway rule points here" and be wrong.
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(screen.queryByText(/putaway rule/)).not.toBeInTheDocument();
  });

  it("counts a rule that names the location second on its list, not first", async () => {
    mockSummary(0, 0);
    // Both rules send goods into the subtree; neither leads with it. Counting
    // by `target_location_id` — the head of the list — finds nothing here and
    // the person archiving is told nothing stops pointing where it pointed.
    mockPutawayRules([
      {
        id: "r1",
        is_active: true,
        target_location_id: "loc-9",
        locations: [
          { location_id: "loc-9", position: 0 },
          { location_id: "zone-1", position: 1 },
        ],
      },
      {
        id: "r2",
        is_active: true,
        target_location_id: "loc-9",
        locations: [
          { location_id: "loc-9", position: 0 },
          { location_id: "loc-1", position: 1 },
        ],
      },
    ]);
    renderDialog();

    expect(
      await screen.findByText(/2 putaway rules point here/),
    ).toBeInTheDocument();
  });

  it("does not ask the warehouse module for rules when it is off", async () => {
    mockSummary(0, 0);
    // Every render asks again, so the answer has to hold for all of them —
    // `mockReturnValueOnce` covers the first render only, and the second one
    // would turn the module back on and fire the request after all.
    enabledModulesMock.mockReturnValue(["core", "items", "locations"]);
    const asked = vi.fn();
    server.use(
      http.get("*/api/v1/warehouse/putaway-rules", () => {
        asked();
        return HttpResponse.json(
          onePage([
            { id: "r1", is_active: true, target_location_id: "zone-1" },
          ]),
        );
      }),
    );
    renderDialog();

    await waitFor(() => expect(confirmButton()).toBeEnabled());
    expect(asked).not.toHaveBeenCalled();
    expect(screen.queryByText(/putaway rule/)).not.toBeInTheDocument();
    enabledModulesMock.mockReturnValue(["warehouse"]);
  });

  it("stays silent when no active rule points into the subtree", async () => {
    mockSummary(0, 0);
    mockPutawayRules([
      { id: "r1", is_active: true, target_location_id: "loc-9" },
    ]);
    renderDialog();

    await waitFor(() => expect(confirmButton()).toBeEnabled());
    expect(screen.queryByText(/putaway rule/)).not.toBeInTheDocument();
  });
});

describe("StorageArchiveDialog", () => {
  it("shows the target picker when items live only in descendant locations", async () => {
    mockSummary(0, 3);
    renderDialog();

    expect(await screen.findByText("Move products to")).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toBeInTheDocument();
  });

  it("asks a plain question when the whole subtree is empty", async () => {
    mockSummary(0, 0);
    renderDialog();

    await waitFor(() => expect(confirmButton()).toBeEnabled());
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("excludes the archived node and its descendants from the targets", async () => {
    mockSummary(0, 3);
    renderDialog();
    await userEvent.click(await screen.findByRole("combobox"));

    expect(
      await screen.findByRole("button", { name: /Shelf B/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Fridge A/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Cold Storage/ })).toBeNull();
    // A place with places inside it is not a destination for records.
    expect(screen.queryByRole("button", { name: /Main Warehouse/ })).toBeNull();
  });

  it("names each target by its path, not by its bare name", async () => {
    mockSummary(0, 3);
    // Two shelves called "Top", in different storages. A list of names shows
    // the same entry twice and the reader cannot tell which one the items
    // would land in.
    renderDialog([
      ...FLOOR.slice(0, 3),
      { id: "bay-1", name: "Bay 3", parent_id: "site-1", is_leaf: false },
      { id: "loc-2", name: "Top", parent_id: "bay-1" },
      { id: "site-2", name: "Annexe", parent_id: null, is_leaf: false },
      { id: "loc-3", name: "Top", parent_id: "site-2" },
    ]);
    await userEvent.click(await screen.findByRole("combobox"));

    const tops = await screen.findAllByRole("button", { name: /^Top/ });
    expect(tops.map((button) => button.textContent).sort()).toEqual([
      "TopAnnexe",
      "TopMain Warehouse › Bay 3",
    ]);
  });

  it("finds a target by asking the server, not by loading every location", async () => {
    mockSummary(0, 3);
    const { requests } = renderDialog([
      ...FLOOR,
      ...Array.from({ length: 300 }, (_, i) => ({
        id: `shelf-${i}`,
        name: `Bin ${i}`,
        parent_id: "site-2",
      })),
      { id: "site-2", name: "Annexe", parent_id: null, is_leaf: false },
    ]);
    await userEvent.click(await screen.findByRole("combobox"));
    // One paste, not seven keystrokes: each key re-renders the open list and
    // restarts the picker's debounce, so typing is what a loaded run races.
    await userEvent.click(screen.getByPlaceholderText(/search/i));
    await userEvent.paste("Bin 299");

    // Wait on the request the server was asked, then on what it answered.
    await waitFor(() =>
      expect(requests.some((r) => r.get("q") === "Bin 299")).toBe(true),
    );
    expect(
      await screen.findByRole("button", { name: /Bin 299/ }),
    ).toBeInTheDocument();
    expect(
      requests
        .filter((r) => !r.has("q") && !r.has("depth"))
        .every((r) => Number(r.get("limit")) <= 100),
    ).toBe(true);
  });

  it("keeps confirming blocked until a target is chosen", async () => {
    mockSummary(0, 3);
    renderDialog();
    await userEvent.click(await screen.findByRole("combobox"));

    expect(confirmButton()).toBeDisabled();
    await userEvent.click(
      await screen.findByRole("button", { name: /Shelf B/ }),
    );
    expect(confirmButton()).toBeEnabled();
  });

  it("keeps the only way out on screen when the summary cannot be read", async () => {
    // A failed read used to be filed as "empty": the picker disappeared,
    // Archive stayed enabled, and the backend then refused to archive a
    // location holding items — with nothing on the screen to fix it.
    server.use(
      http.get("*/api/v1/locations/:id/summary", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
      http.get("*/api/v1/warehouse/putaway-rules", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    renderDialog();

    expect(await screen.findByRole("combobox")).toBeInTheDocument();
    expect(
      screen.getByText(/Could not check what this location holds/),
    ).toBeInTheDocument();
  });

  it("does not demand a target it cannot prove is needed", async () => {
    server.use(
      http.get("*/api/v1/locations/:id/summary", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
      http.get("*/api/v1/warehouse/putaway-rules", () =>
        HttpResponse.json(onePage([])),
      ),
    );
    renderDialog();

    await screen.findByRole("combobox");
    expect(confirmButton()).toBeEnabled();
  });

  it("archives with the chosen target location", async () => {
    mockSummary(0, 3);
    let archiveBody: unknown = null;
    server.use(
      http.post("*/api/v1/locations/:id/archive", async ({ request }) => {
        archiveBody = await request.json();
        return HttpResponse.json({ id: "zone-1" });
      }),
    );
    const { onOpenChange, onArchived } = renderDialog();

    await userEvent.click(await screen.findByRole("combobox"));
    await userEvent.click(
      await screen.findByRole("button", { name: /Shelf B/ }),
    );
    fireEvent.click(confirmButton());

    await waitFor(() => expect(onArchived).toHaveBeenCalledOnce());
    expect(archiveBody).toEqual({ move_items_to: "loc-9" });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("closes without archiving when Cancel is pressed", async () => {
    mockSummary(0, 0);
    const archived = vi.fn();
    server.use(
      http.post("*/api/v1/locations/:id/archive", () => {
        archived();
        return HttpResponse.json({ id: "zone-1" });
      }),
    );
    const { onOpenChange, onArchived } = renderDialog();
    await waitFor(() => expect(confirmButton()).toBeEnabled());

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onArchived).not.toHaveBeenCalled();
    expect(archived).not.toHaveBeenCalled();
  });

  it("still asks the plain question when the putaway rules cannot be read, without a rule count", async () => {
    server.use(
      http.get("*/api/v1/locations/:id/summary", ({ params }) =>
        HttpResponse.json({
          id: params.id,
          name: "Cold Storage",
          items_count: 0,
          subtree_items_count: 0,
          children_count: 0,
        }),
      ),
      http.get("*/api/v1/warehouse/putaway-rules", () =>
        HttpResponse.json({ detail: "down" }, { status: 500 }),
      ),
    );
    renderDialog();

    await waitFor(() => expect(confirmButton()).toBeEnabled());
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(screen.queryByText(/putaway rule/)).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });
});
