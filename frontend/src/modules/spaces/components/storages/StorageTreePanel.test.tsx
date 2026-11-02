import { render, screen, waitFor } from "@/test/utils";
import { describe, it, expect, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { serveLocations } from "@/test/serveLocations";
import { StorageTreePanel } from "./StorageTreePanel";

// Pantry Building › Dry Goods › Shelf A › Bin 1, and a second building with
// enough shelves that nobody should be reading them all.
const FLOOR = [
  { id: "site", name: "Pantry Building", parent_id: null },
  { id: "zone", name: "Dry Goods", parent_id: "site" },
  { id: "shelf", name: "Shelf A", parent_id: "zone" },
  { id: "bin", name: "Bin 1", parent_id: "shelf" },
  { id: "annexe", name: "Annexe", parent_id: null },
  ...Array.from({ length: 300 }, (_, i) => ({
    id: `row-${i}`,
    name: `Row ${i}`,
    parent_id: "annexe",
  })),
];

function renderPanel(
  extra: Partial<React.ComponentProps<typeof StorageTreePanel>> = {},
) {
  const onSelect = vi.fn();
  render(
    <StorageTreePanel
      excludeModuleContexts
      onSelect={onSelect}
      canWrite={false}
      onMoveTo={vi.fn()}
      onDragMove={vi.fn()}
      {...extra}
    />,
  );
  return onSelect;
}

describe("StorageTreePanel — the tree holds the levels that were opened", () => {
  it("reads the top level first and a branch only when its row is opened", async () => {
    const requests = serveLocations(FLOOR);
    renderPanel();

    expect(
      await screen.findByRole("treeitem", { name: /Pantry Building/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("treeitem", { name: /Dry Goods/ })).toBeNull();
    // 300 rows stand under the annexe; none of them was asked for.
    expect(requests.map((r) => [r.get("parent_id"), r.get("depth")])).toEqual([
      [null, "1"],
    ]);

    await userEvent.click(
      screen.getByRole("button", { name: "Expand Pantry Building" }),
    );
    expect(
      await screen.findByRole("treeitem", { name: /Dry Goods/ }),
    ).toBeInTheDocument();
    expect(requests.at(-1)?.get("parent_id")).toBe("site");
    expect(requests.at(-1)?.get("depth")).toBe("1");
    expect(requests).toHaveLength(2);
  });

  it("opens the branches above a place it arrives at by deep link", async () => {
    serveLocations(FLOOR);
    renderPanel({ selectedId: "shelf", openPath: ["site", "zone"] });

    expect(
      await screen.findByRole("treeitem", { name: /Shelf A/ }),
    ).toHaveAttribute("aria-selected", "true");
  });
});

describe("StorageTreePanel — search is asked of the server", () => {
  it("lists the places that match with the way to each, and selects one", async () => {
    const requests = serveLocations(FLOOR);
    const onSelect = renderPanel();
    await screen.findByRole("treeitem", { name: /Pantry Building/ });

    await userEvent.type(screen.getByPlaceholderText(/search/i), "Bin 1");

    const hit = await screen.findByRole("button", { name: /Bin 1/ });
    expect(hit).toHaveTextContent(
      "Pantry Building → Dry Goods → Shelf A → Bin 1",
    );
    expect(requests.some((r) => r.get("q") === "Bin 1")).toBe(true);
    // Nothing read the tree whole to filter it in the browser.
    expect(requests.every((r) => Number(r.get("limit") ?? 0) <= 200)).toBe(
      true,
    );

    await userEvent.click(hit);
    expect(onSelect).toHaveBeenCalledWith("bin");
  });

  it("says so when nothing matches, and goes back to the tree when cleared", async () => {
    serveLocations(FLOOR);
    renderPanel();
    await screen.findByRole("treeitem", { name: /Pantry Building/ });
    const search = screen.getByPlaceholderText(/search/i);

    await userEvent.type(search, "nowhere");
    expect(await screen.findByText(/No locations match/i)).toBeInTheDocument();

    await userEvent.clear(search);
    await waitFor(() =>
      expect(
        screen.getByRole("treeitem", { name: /Pantry Building/ }),
      ).toBeInTheDocument(),
    );
  });
});

describe("StorageTreePanel — a failed read is not an empty answer", () => {
  it("says a branch could not be read, with a retry, instead of opening onto nothing", async () => {
    serveLocations(FLOOR);
    renderPanel();
    await screen.findByRole("treeitem", { name: /Pantry Building/ });
    let down = true;
    server.use(
      http.get("/api/v1/locations/tree", ({ request }) =>
        down && new URL(request.url).searchParams.has("parent_id")
          ? HttpResponse.json({ detail: "down" }, { status: 500 })
          : undefined,
      ),
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Expand Pantry Building" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "An error occurred",
    );

    down = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(
      await screen.findByRole("treeitem", { name: /Dry Goods/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says the search failed, with a retry, rather than showing nothing", async () => {
    serveLocations(FLOOR);
    renderPanel();
    await screen.findByRole("treeitem", { name: /Pantry Building/ });
    let down = true;
    server.use(
      http.get("/api/v1/locations", ({ request }) =>
        down && new URL(request.url).searchParams.has("q")
          ? HttpResponse.json({ detail: "down" }, { status: 500 })
          : undefined,
      ),
    );

    await userEvent.type(screen.getByPlaceholderText(/search/i), "Bin 1");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "An error occurred",
    );
    expect(screen.queryByText(/No locations match/i)).toBeNull();

    down = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(
      await screen.findByRole("button", { name: /Bin 1/ }),
    ).toBeInTheDocument();
  });
});
