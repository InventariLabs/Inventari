import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { QueryWrapper } from "@/test/queryWrapper";
import { serveLocations } from "@/test/serveLocations";
import { useStorageLocationLabels } from "./useStorageLocationLabels";

// More shelves than a screen should ever download to name two of them.
const SHELVES = Array.from({ length: 600 }, (_, i) => ({
  id: `shelf-${i}`,
  name: `Shelf ${i}`,
  parent_id: "wh",
}));
const FLOOR = [{ id: "wh", name: "Warehouse", parent_id: null }, ...SHELVES];

describe("useStorageLocationLabels", () => {
  it("names the places it was given by their path and reads nothing else", async () => {
    const requests = serveLocations(FLOOR);
    const { result } = renderHook(
      () => useStorageLocationLabels(["shelf-599", "shelf-3"]),
      { wrapper: QueryWrapper },
    );

    await waitFor(() =>
      expect(result.current("shelf-599", "Shelf 599")).toBe(
        "Warehouse › Shelf 599",
      ),
    );
    expect(result.current("shelf-3", null)).toBe("Warehouse › Shelf 3");
    // Two places named: one request for the two, not twelve pages of 600.
    expect(requests).toHaveLength(1);
    expect(requests[0].getAll("ids").sort()).toEqual(["shelf-3", "shelf-599"]);
  });

  it("keeps the name the row came with until the place is known", () => {
    serveLocations(FLOOR);
    const { result } = renderHook(() => useStorageLocationLabels(["shelf-1"]), {
      wrapper: QueryWrapper,
    });

    expect(result.current("shelf-1", "Shelf 1")).toBe("Shelf 1");
    expect(result.current(null, null)).toBeNull();
  });
});
