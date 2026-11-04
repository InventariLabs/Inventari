import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { QueryWrapper } from "@/test/queryWrapper";
import { serveLocations } from "@/test/serveLocations";
import { useLocationOffer, useLocationsById } from "./useLocations";

// An organization with more shelves than a screen should ever hold.
const SHELVES = Array.from({ length: 400 }, (_, i) => ({
  id: `shelf-${i}`,
  name: `Shelf ${i}`,
  parent_id: "wh",
}));
const FLOOR = [{ id: "wh", name: "Warehouse", parent_id: null }, ...SHELVES];

describe("useLocationsById", () => {
  it("names the places it was given and nothing else", async () => {
    const requests = serveLocations(FLOOR);
    const { result } = renderHook(
      () => useLocationsById(["shelf-399", "shelf-7", "shelf-7", null]),
      { wrapper: QueryWrapper },
    );

    await waitFor(() => expect(result.current.byId.size).toBe(2));
    expect(result.current.byId.get("shelf-399")?.full_path).toBe(
      "Warehouse › Shelf 399",
    );
    expect(requests).toHaveLength(1);
    expect(requests[0].getAll("ids")).toEqual(["shelf-399", "shelf-7"]);
    expect(requests[0].get("counts")).toBe("false");
    // Archived and virtual places are nameable: a record may stand in one.
    expect(requests[0].get("usage")).toBe("all");
    expect(requests[0].get("include_archived")).toBe("true");
  });

  it("asks nothing when there is nothing to name", () => {
    const requests = serveLocations(FLOOR);
    renderHook(() => useLocationsById([undefined, null]), {
      wrapper: QueryWrapper,
    });

    expect(requests).toHaveLength(0);
  });

  it("splits a long list of ids over requests the endpoint accepts", async () => {
    const requests = serveLocations(FLOOR);
    const { result } = renderHook(
      () => useLocationsById(SHELVES.map((shelf) => shelf.id)),
      { wrapper: QueryWrapper },
    );

    await waitFor(() => expect(result.current.byId.size).toBe(400));
    expect(requests).toHaveLength(4);
    expect(Math.max(...requests.map((r) => r.getAll("ids").length))).toBe(100);
  });
});

describe("useLocationOffer", () => {
  it("counts what a scope offers from two rows, not from the list", async () => {
    const requests = serveLocations(FLOOR);
    const { result } = renderHook(
      () => useLocationOffer({ purpose: "stock" }),
      {
        wrapper: QueryWrapper,
      },
    );

    await waitFor(() => expect(result.current.total).toBe(401));
    expect(result.current.first).toHaveLength(2);
    expect(result.current.emptyReason).toBeNull();
    expect(requests).toHaveLength(1);
    expect(requests[0].get("limit")).toBe("2");
    expect(requests[0].get("exclude_module_contexts")).toBe("true");
  });

  it("says nothing is on offer when the organization has no place", async () => {
    serveLocations([]);
    const { result } = renderHook(
      () => useLocationOffer({ purpose: "stock" }),
      {
        wrapper: QueryWrapper,
      },
    );

    await waitFor(() =>
      expect(result.current.emptyReason).toBe("nothing-to-offer"),
    );
  });

  it("names the policy when module places are all there is", async () => {
    serveLocations([{ id: "rack", name: "Rack", context_tag: "equipment" }]);
    const { result } = renderHook(() => useLocationOffer({}), {
      wrapper: QueryWrapper,
    });

    await waitFor(() =>
      expect(result.current.emptyReason).toBe("module-data-hidden"),
    );
  });

  it("does not name the policy when only archived or virtual rows stand outside the list", async () => {
    // The module-data switch would reveal neither: the probe asks with the
    // scope's own usage and archive filter, and drops only the exclusion.
    serveLocations([
      {
        id: "old",
        name: "Old rack",
        context_tag: "equipment",
        settings: { archived: true },
      },
      { id: "scrap", name: "Scrap", context_tag: "equipment", usage: "scrap" },
    ]);
    const { result } = renderHook(() => useLocationOffer({}), {
      wrapper: QueryWrapper,
    });

    await waitFor(() =>
      expect(result.current.emptyReason).toBe("nothing-to-offer"),
    );
  });
});
