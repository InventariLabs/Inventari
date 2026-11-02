import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MoveItemModal } from "./MoveItemModal";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import type { Item } from "@/types";

// The two lists a move can be offered: the form's picker asks without the
// module-owned locations, the raw list carries them too.
const internalShelf = {
  id: "loc-internal",
  name: "Cold Storage",
  parent_id: null,
  is_leaf: true,
  usage: "internal",
  location_type: { icon: "Snowflake" },
};
const moduleRack = {
  id: "loc-rack",
  name: "Server Rack A",
  parent_id: null,
  is_leaf: true,
  usage: "internal",
  context_tag: "equipment",
  location_type: { icon: "Server" },
};
// A location with sublocations under it: the API says so with is_leaf.
const garageWithShelves = {
  id: "loc-garage",
  name: "Garage",
  parent_id: null,
  is_leaf: false,
  usage: "internal",
  location_type: { icon: "Warehouse" },
};
const currentSpot = {
  id: "loc-home",
  name: "Home Shelf",
  parent_id: null,
  is_leaf: true,
  usage: "internal",
  context_tag: "equipment",
  location_type: { icon: "Package" },
};

// A food-behaviour location carries the tag "food" — a kind of place, not a
// module, so there is nobody to name on a badge. It sits two levels down so
// the picker has a path to caption it with.
const foodFridge = {
  id: "loc-fridge",
  name: "Fridge A - Top Shelf",
  parent_id: "loc-internal",
  full_path: "Cold Storage → Fridge A - Top Shelf",
  is_leaf: true,
  usage: "internal",
  context_tag: "food",
  location_type: { icon: "Snowflake" },
};

const item = {
  id: "item-1",
  name: "Butter",
  quantity: 1,
  location_id: "loc-home",
} as unknown as Item;

// What the endpoint answers: a search is the offered set (a stock flow's ask
// leaves the module's places out), naming by id reaches every place.
function mockStorages() {
  const everything = [
    internalShelf,
    moduleRack,
    garageWithShelves,
    currentSpot,
    foodFridge,
  ];
  const offered = [internalShelf, foodFridge, garageWithShelves];
  server.use(
    http.get("/api/v1/locations", ({ request }) => {
      const params = new URL(request.url).searchParams;
      const ids = params.getAll("ids");
      const needle = (params.get("q") ?? "").toLowerCase();
      const pool = ids.length
        ? everything.filter((row) => ids.includes(row.id))
        : params.get("exclude_module_contexts")
          ? offered
          : everything;
      const rows = pool.filter((row) =>
        row.name.toLowerCase().includes(needle),
      );
      return HttpResponse.json({
        items: rows,
        total: rows.length,
        limit: Number(params.get("limit") ?? 50),
        offset: 0,
        has_more: false,
      });
    }),
  );
}

const renderModal = () => {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MoveItemModal item={item} onClose={vi.fn()} onSuccess={vi.fn()} />
    </QueryClientProvider>,
  );
};

describe("MoveItemModal — one question, one answer", () => {
  beforeEach(() => {
    mockStorages();
  });

  it("offers the form's scope, not the raw list", async () => {
    const user = userEvent.setup();
    renderModal();
    // The trigger's accessible name gets hidden from role queries while the
    // Radix sheet around it is open — match the visible value instead.
    const trigger = (await screen.findByText("Home Shelf")).closest(
      "button",
    ) as HTMLButtonElement;
    expect(trigger).not.toBeNull();

    await user.click(trigger);

    // The module rack the raw list would have offered — butter on a server
    // shelf — is not in the picker; the internal shelf is.
    expect(await screen.findByText("Garage")).toBeInTheDocument();
    expect(screen.getAllByText("Cold Storage").length).toBeGreaterThan(0);
    expect(screen.queryByText("Server Rack A")).not.toBeInTheDocument();
    // The place the item stands in stays selectable (keepId) — trigger and
    // option both show it once the panel is open.
    expect(screen.getAllByText("Home Shelf").length).toBeGreaterThan(0);
  });

  it("offers a location that has sublocations under it (ADR-018)", async () => {
    const user = userEvent.setup();
    renderModal();
    const trigger = (await screen.findByText("Home Shelf")).closest(
      "button",
    ) as HTMLButtonElement;

    await user.click(trigger);

    // "Leaf" used to decide this. It cannot: a shelf stops being one the
    // moment somebody puts a box under it, and the thing already on it would
    // vanish from the picker that moves it.
    expect(await screen.findByText("Garage")).toBeInTheDocument();
  });

  it("says whose a module-owned location is, like the other pickers do", async () => {
    // Seven pickers of the eight badge them; this sheet showed the same
    // locations bare — and it is the window where somebody decides where the
    // goods go. The item's own shelf is module-owned and stays selectable, so
    // the sheet offers one whether or not the organization mixes lists.
    const user = userEvent.setup();
    renderModal();
    const trigger = (await screen.findByText("Home Shelf")).closest(
      "button",
    ) as HTMLButtonElement;

    await user.click(trigger);

    expect(
      await screen.findByText("Module: Equipment Tracking"),
    ).toBeInTheDocument();
  });

  it("refuses a move that changes nothing", async () => {
    renderModal();
    await screen.findByText("Home Shelf");
    // Move without changing the choice is a no-op — the button knows it.
    const moveButton = screen.getByRole("button", { name: /^move$/i });
    expect(moveButton).toBeDisabled();
  });

  it("asks with the searchable picker, not a bare select", async () => {
    const user = userEvent.setup();
    renderModal();
    const trigger = (await screen.findByText("Home Shelf")).closest(
      "button",
    ) as HTMLButtonElement;

    await user.click(trigger);
    expect(await screen.findByPlaceholderText(/search/i)).toBeInTheDocument();
  });

  it("titles a nested location with its own name and captions it with the path", async () => {
    // The whole path as the title lost its end to the clip on a phone — the
    // end being the only part that tells two shelves apart.
    const user = userEvent.setup();
    renderModal();
    const trigger = (await screen.findByText("Home Shelf")).closest(
      "button",
    ) as HTMLButtonElement;

    await user.click(trigger);

    const title = await screen.findByText("Fridge A - Top Shelf");
    expect(title).toBeInTheDocument();
    // The caption is the way to the place — the places above it, not the
    // place again.
    expect(title.closest("button")).toHaveTextContent(
      "Fridge A - Top ShelfCold Storage",
    );
  });

  it("does not claim a module owns a location whose tag is not a module", async () => {
    // "food" is stamped on EXPIRY/FREEZING locations by the backend; no
    // module has that name, and the badge used to print the raw tag.
    const user = userEvent.setup();
    renderModal();
    const trigger = (await screen.findByText("Home Shelf")).closest(
      "button",
    ) as HTMLButtonElement;

    await user.click(trigger);
    await screen.findByText("Fridge A - Top Shelf");

    expect(screen.queryByText(/Module: food/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/food/i)).not.toBeInTheDocument();
  });
});
