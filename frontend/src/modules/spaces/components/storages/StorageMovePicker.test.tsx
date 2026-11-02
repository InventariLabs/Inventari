import { render, screen } from "@/test/utils";
import { describe, it, expect, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { serveLocations } from "@/test/serveLocations";
import { StorageMovePicker } from "./StorageMovePicker";

const FLOOR = [
  { id: "site", name: "Pantry Building", parent_id: null },
  { id: "zone", name: "Dry Goods", parent_id: "site" },
  { id: "shelf", name: "Shelf A", parent_id: "zone" },
  { id: "bin", name: "Bin 1", parent_id: "shelf" },
  { id: "cold", name: "Cold Room", parent_id: null },
];

function renderPicker(movingIds: string[]) {
  const onPick = vi.fn();
  render(
    <StorageMovePicker
      open
      movingIds={movingIds}
      excludeModuleContexts
      onClose={vi.fn()}
      onPick={onPick}
    />,
  );
  return onPick;
}

describe("StorageMovePicker — destinations come a level at a time", () => {
  it("opens on the top level without the place being moved", async () => {
    const requests = serveLocations(FLOOR);
    renderPicker(["cold"]);

    expect(
      await screen.findByRole("treeitem", { name: /Pantry Building/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("treeitem", { name: /Cold Room/ })).toBeNull();
    // Nothing below the top level was read before the reader opened it; the
    // other read names the place being moved.
    expect(requests.filter((r) => r.has("depth"))).toHaveLength(1);
    expect(requests.find((r) => r.has("depth"))?.get("depth")).toBe("1");
    expect(
      requests.filter((r) => !r.has("depth")).map((r) => r.getAll("ids")),
    ).toEqual([["cold"]]);
  });

  it("picks a destination after opening the branch that holds it", async () => {
    serveLocations(FLOOR);
    const onPick = renderPicker(["cold"]);
    await userEvent.click(
      await screen.findByRole("button", { name: "Expand Pantry Building" }),
    );

    await userEvent.click(
      await screen.findByRole("treeitem", { name: /Dry Goods/ }),
    );
    expect(onPick).toHaveBeenCalledWith("zone");
  });
});

describe("StorageMovePicker — a search leaves out what cannot be a destination", () => {
  it("never offers the moved place, what stands inside it, ", async () => {
    const requests = serveLocations(FLOOR);
    renderPicker(["zone"]);
    await screen.findByRole("treeitem", { name: /Pantry Building/ });

    // "r" is in every path: the server answers with all of them.
    await userEvent.type(screen.getByPlaceholderText(/search/i), "r");

    expect(
      await screen.findByRole("button", { name: /Cold Room/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Dry Goods/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Shelf A/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Bin 1/ })).toBeNull();
    expect(requests.some((r) => r.get("q") === "r")).toBe(true);
  });
});

describe("StorageMovePicker — a failed search is not an empty one", () => {
  it("says the search failed, with a retry, rather than that nothing matches", async () => {
    serveLocations(FLOOR);
    renderPicker(["cold"]);
    await screen.findByRole("treeitem", { name: /Pantry Building/ });
    server.use(
      http.get("/api/v1/locations", ({ request }) =>
        new URL(request.url).searchParams.has("q")
          ? HttpResponse.json({ detail: "down" }, { status: 500 })
          : undefined,
      ),
    );

    await userEvent.type(screen.getByPlaceholderText(/search/i), "r");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "An error occurred",
    );
    expect(
      screen.getByRole("button", { name: "Try again" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/no matches/i)).toBeNull();
  });
});

describe("StorageMovePicker — a failed level is not an empty one", () => {
  it("says a branch could not be read, with a retry", async () => {
    serveLocations(FLOOR);
    renderPicker(["cold"]);
    await screen.findByRole("treeitem", { name: /Pantry Building/ });
    server.use(
      http.get("/api/v1/locations/tree", ({ request }) =>
        new URL(request.url).searchParams.has("parent_id")
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
    expect(
      screen.getByRole("button", { name: "Try again" }),
    ).toBeInTheDocument();
  });
});

describe("StorageMovePicker — choosing where it goes", () => {
  it("moves to the top level when 'Top level' is pressed, not under any place", async () => {
    serveLocations(FLOOR);
    const onPick = renderPicker(["zone"]);
    await screen.findByRole("treeitem", { name: /Pantry Building/ });

    await userEvent.click(screen.getByRole("button", { name: "Top level" }));

    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick).toHaveBeenCalledWith(null);
  });

  it("picks the search result that was pressed, with its own id", async () => {
    serveLocations(FLOOR);
    const onPick = renderPicker(["zone"]);
    await screen.findByRole("treeitem", { name: /Pantry Building/ });

    await userEvent.type(screen.getByPlaceholderText(/search/i), "Cold");
    await userEvent.click(
      await screen.findByRole("button", { name: /Cold Room/ }),
    );

    expect(onPick).toHaveBeenCalledWith("cold");
  });

  it("reads the search again when 'Try again' is pressed after it failed, and then lists the match", async () => {
    serveLocations(FLOOR);
    renderPicker(["zone"]);
    await screen.findByRole("treeitem", { name: /Pantry Building/ });
    let failing = true;
    server.use(
      http.get("/api/v1/locations", ({ request }) =>
        failing && new URL(request.url).searchParams.has("q")
          ? HttpResponse.json({ detail: "down" }, { status: 500 })
          : undefined,
      ),
    );

    await userEvent.type(screen.getByPlaceholderText(/search/i), "Cold");
    const retry = await screen.findByRole("button", { name: "Try again" });
    failing = false;
    await userEvent.click(retry);

    expect(
      await screen.findByRole("button", { name: /Cold Room/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
