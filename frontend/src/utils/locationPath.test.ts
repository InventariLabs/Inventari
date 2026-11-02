/**
 * One format for a location path, everywhere it is shown.
 *
 * A path is what tells two shelves called "Top" apart. Screens wrote it
 * three ways: the backend composes `full_path` with " → ", the document form
 * joined its own segments with " / ", and the archive dialog showed no path
 * at all — a list of bare names where the target could not be identified.
 */
import { describe, expect, it } from "vitest";

import {
  LOCATION_PATH_SEPARATOR,
  getStorageLocationPath,
  locationPathBelowName,
  splitLocationPath,
} from "./helpers";

const shelf = {
  id: "loc-1",
  name: "Top",
  full_path: "Main Warehouse → Bay 3 → Top",
};

describe("the location path is written one way", () => {
  it("uses the separator the backend composes paths with", () => {
    // storage_query_service._compute_full_path joins with this exact string.
    expect(LOCATION_PATH_SEPARATOR).toBe(" → ");
  });

  it("shows the whole path, not just the last segment", () => {
    expect(getStorageLocationPath(shelf)).toBe("Main Warehouse → Bay 3 → Top");
  });

  it("appends a shelf with the same separator", () => {
    expect(getStorageLocationPath(shelf, "second from the left")).toBe(
      "Main Warehouse → Bay 3 → Top → second from the left",
    );
  });

  it("says nothing under a root whose path is its own name", () => {
    expect(
      locationPathBelowName({
        name: "Main Warehouse",
        full_path: "Main Warehouse",
      }),
    ).toBeUndefined();
  });

  it("says the path under a nested location", () => {
    expect(locationPathBelowName(shelf)).toBe("Main Warehouse → Bay 3 → Top");
  });

  it("says nothing when the backend sent no path", () => {
    expect(locationPathBelowName({ name: "Top" })).toBeUndefined();
  });
});

/**
 * Not every screen holds a record the backend put `full_path` on. The list
 * endpoint sends one (`StorageLocationSummary`), but several callers hold the
 * plainer `StorageLocation`, and the product list used to print the bare
 * `storage.name` for those — "Shelf A - Top" with no sign of which warehouse
 * it stands in. When the caller passes the list it already has, the path can
 * be rebuilt from `parent_id` instead of being given up on.
 */
describe("a path with no backend full_path is rebuilt from the list", () => {
  const storages = [
    { id: "site-1", name: "Main Warehouse", parent_id: null },
    { id: "bay-3", name: "Bay 3", parent_id: "site-1" },
    { id: "top", name: "Top", parent_id: "bay-3" },
    { id: "root", name: "Receiving", parent_id: null },
  ];

  it("walks the ancestors up to the root", () => {
    expect(getStorageLocationPath(storages[2], null, undefined, storages)).toBe(
      "Main Warehouse → Bay 3 → Top",
    );
  });

  it("appends the shelf after the walked path", () => {
    expect(
      getStorageLocationPath(
        storages[2],
        "second from the left",
        undefined,
        storages,
      ),
    ).toBe("Main Warehouse → Bay 3 → Top → second from the left");
  });

  it("leaves a root storage as its own name", () => {
    expect(getStorageLocationPath(storages[3], null, undefined, storages)).toBe(
      "Receiving",
    );
  });

  it("prefers the backend path over the walk when both are available", () => {
    expect(
      getStorageLocationPath(
        { ...storages[2], full_path: "Elsewhere → Top" },
        null,
        undefined,
        storages,
      ),
    ).toBe("Elsewhere → Top");
  });

  it("stops at the last known ancestor rather than inventing one", () => {
    const orphan = { id: "x", name: "Top", parent_id: "gone" };
    expect(getStorageLocationPath(orphan, null, undefined, storages)).toBe(
      "Top",
    );
  });

  it("terminates on legacy rows that point at each other", () => {
    const cycle = [
      { id: "a", name: "A", parent_id: "b" },
      { id: "b", name: "B", parent_id: "a" },
    ];
    expect(getStorageLocationPath(cycle[0], null, undefined, cycle)).toBe(
      "B → A",
    );
  });
});

describe("a path is split into the leaf and the road to it", () => {
  it("puts the last segment first and the rest behind it", () => {
    expect(splitLocationPath("Pantry Building → Dry Goods → Shelf A")).toEqual({
      leaf: "Shelf A",
      parents: "Pantry Building → Dry Goods",
    });
  });

  it("has no road for a place at the root", () => {
    expect(splitLocationPath("Pantry Building")).toEqual({
      leaf: "Pantry Building",
      parents: null,
    });
  });
});
