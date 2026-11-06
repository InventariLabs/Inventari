import React from "react";
import { renderHook, act } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, it, expect } from "vitest";
import { useItemFilters } from "./useItemFilters";

const wrapper =
  (search = "") =>
  ({ children }: { children: React.ReactNode }) =>
    React.createElement(MemoryRouter, { initialEntries: [search] }, children);

describe("useItemFilters", () => {
  it("initializes with default empty state", () => {
    const { result } = renderHook(() => useItemFilters(), {
      wrapper: wrapper(),
    });

    expect(result.current.searchInput).toBe("");
    expect(result.current.search).toBe("");
    expect(result.current.storageFilter).toBe("");
    expect(result.current.categoryFilter).toBe("");
    expect(result.current.expiringFilter).toBe(false);
    expect(result.current.expiredFilter).toBe(false);
    expect(result.current.lowStockFilter).toBe(false);
    expect(result.current.showFilters).toBe(false);
    expect(result.current.skip).toBe(0);
    expect(result.current.limit).toBe(50);
  });

  it("setStorageFilter updates storageFilter", () => {
    const { result } = renderHook(() => useItemFilters(), {
      wrapper: wrapper(),
    });
    act(() => result.current.setStorageFilter("storage-1"));
    expect(result.current.storageFilter).toBe("storage-1");
  });

  it("setCategoryFilter updates categoryFilter", () => {
    const { result } = renderHook(() => useItemFilters(), {
      wrapper: wrapper(),
    });
    act(() => result.current.setCategoryFilter("cat-1"));
    expect(result.current.categoryFilter).toBe("cat-1");
  });

  it("setExpiringFilter updates expiringFilter", () => {
    const { result } = renderHook(() => useItemFilters(), {
      wrapper: wrapper(),
    });
    act(() => result.current.setExpiringFilter(true));
    expect(result.current.expiringFilter).toBe(true);
  });

  it("turning one date chip on turns the other off", () => {
    const { result } = renderHook(() => useItemFilters(), {
      wrapper: wrapper(),
    });
    act(() => result.current.setExpiredFilter(true));
    act(() => result.current.setExpiringFilter(true));
    expect(result.current.expiringFilter).toBe(true);
    expect(result.current.expiredFilter).toBe(false);

    act(() => result.current.setExpiredFilter(true));
    expect(result.current.expiredFilter).toBe(true);
    expect(result.current.expiringFilter).toBe(false);
  });

  it("resetting filter resets skip to 0", () => {
    const { result } = renderHook(() => useItemFilters(), {
      wrapper: wrapper(),
    });
    act(() => result.current.setSkip(50));
    act(() => result.current.setCategoryFilter("cat-1"));
    expect(result.current.skip).toBe(0);
  });

  it("initializes expiringFilter from ?filter=expiring URL param", () => {
    const { result } = renderHook(() => useItemFilters(), {
      wrapper: wrapper("/?filter=expiring"),
    });
    expect(result.current.expiringFilter).toBe(true);
    // The chip says it; the pickers stay shut so the list is what opens.
    expect(result.current.showFilters).toBe(false);
  });

  it("initializes lowStockFilter from ?filter=low-stock URL param", () => {
    const { result } = renderHook(() => useItemFilters(), {
      wrapper: wrapper("/?filter=low-stock"),
    });
    expect(result.current.lowStockFilter).toBe(true);
    expect(result.current.showFilters).toBe(false);
  });

  it("initializes storageFilter from ?location_id URL param", () => {
    const { result } = renderHook(() => useItemFilters(), {
      wrapper: wrapper("/?location_id=s-123"),
    });
    expect(result.current.storageFilter).toBe("s-123");
    expect(result.current.showFilters).toBe(true);
  });

  it("keeps the picker panel closed when a status chip is ticked", () => {
    // A chip writes ?filter= to the address; that is the reader's own click,
    // not a link arriving, and the panel only holds the place and category
    // pickers, so opening it pushed the list down for nothing.
    const { result } = renderHook(() => useItemFilters(), {
      wrapper: wrapper("/"),
    });
    act(() => result.current.setExpiredFilter(true));
    expect(result.current.expiredFilter).toBe(true);
    expect(result.current.showFilters).toBe(false);
  });

  it("stays on the page it was asked for", () => {
    // The "reset paging when the sort changes" effect listed the whole filter
    // object in its dependencies, and that object is rebuilt on every render —
    // so every render reset the offset and the list could not leave page 1.
    const { result } = renderHook(() => useItemFilters(), {
      wrapper: wrapper("/"),
    });

    act(() => result.current.setSkip(result.current.limit));

    expect(result.current.skip).toBe(result.current.limit);
  });

  it("returns to the first page when the sort changes", () => {
    const { result } = renderHook(() => useItemFilters(), {
      wrapper: wrapper("/"),
    });
    act(() => result.current.setSkip(result.current.limit));

    act(() => result.current.setSort("name", "asc"));

    expect(result.current.skip).toBe(0);
  });

  it("writes the sort into the address and reads it back", () => {
    const { result } = renderHook(
      () => ({ filters: useItemFilters(), location: useLocation() }),
      { wrapper: wrapper("/inventory/items?filter=low-stock") },
    );

    act(() => result.current.filters.setSort("name", "asc"));

    const params = new URLSearchParams(result.current.location.search);
    expect(params.get("sort_by")).toBe("name");
    expect(params.get("sort_order")).toBe("asc");
    // The narrowing already in the address is left alone.
    expect(params.get("filter")).toBe("low-stock");

    // The default order is not worth an address of its own.
    act(() => result.current.filters.setSort("created_at", "desc"));
    const back = new URLSearchParams(result.current.location.search);
    expect(back.has("sort_by")).toBe(false);
    expect(back.has("sort_order")).toBe(false);
    expect(back.get("filter")).toBe("low-stock");
  });

  // A chip and a sort pressed before the first address has rendered each
  // start from the address on screen; the sort used to write past the list's
  // own queue of writes, so the chip stayed on while Back lost it.
  it.each([
    ["chip first", ["chip", "sort"]],
    ["sort first", ["sort", "chip"]],
  ])(
    "keeps a chip and a sort pressed in one moment both in the address (%s)",
    async (_name, order) => {
      const { result } = renderHook(
        () => ({ filters: useItemFilters(), location: useLocation() }),
        { wrapper: wrapper("/inventory/items") },
      );

      await act(async () => {
        for (const press of order) {
          if (press === "chip") result.current.filters.setExpiredFilter(true);
          else result.current.filters.setSort("name", "asc");
          await Promise.resolve();
        }
      });

      const params = new URLSearchParams(result.current.location.search);
      expect(params.get("filter")).toBe("expired");
      expect(params.get("sort_by")).toBe("name");
      expect(params.get("sort_order")).toBe("asc");
      expect(result.current.filters.expiredFilter).toBe(true);
    },
  );

  it("opens in the order the address names", () => {
    const { result } = renderHook(() => useItemFilters(), {
      wrapper: wrapper("/inventory/items?sort_by=name&sort_order=asc"),
    });
    expect(result.current.sortBy).toBe("name");
    expect(result.current.sortOrder).toBe("asc");
  });

  it("names the address's order on the first render, not after an effect", () => {
    const seen: string[] = [];
    renderHook(
      () => {
        const f = useItemFilters();
        seen.push(`${f.sortBy}:${f.sortOrder}`);
        return f;
      },
      { wrapper: wrapper("/inventory/items?sort_by=name&sort_order=asc") },
    );
    expect(seen[0]).toBe("name:asc");
  });

  it("returns to the first page when the page size changes", () => {
    // Page 4 of 50-row pages is past the end once a page holds 200, and
    // offset 150 into 200-row pages skips rows outright.
    const { result } = renderHook(() => useItemFilters(), {
      wrapper: wrapper("/"),
    });

    act(() => result.current.setSkip(150));
    expect(result.current.skip).toBe(150);

    act(() => result.current.setLimit(200));

    expect(result.current.limit).toBe(200);
    expect(result.current.skip).toBe(0);
  });

  it("writes what is typed and ticked into the address, so Back finds the list narrowed", () => {
    const { result } = renderHook(
      () => ({ filters: useItemFilters(), location: useLocation() }),
      { wrapper: wrapper("/inventory/items") },
    );

    act(() => result.current.filters.setSearchInput("Damson"));
    act(() => result.current.filters.setExpiringFilter(true));
    expect(result.current.location.search).toContain("search=Damson");
    expect(result.current.location.search).toContain("filter=expiring");

    act(() => result.current.filters.clearFilters());
    expect(result.current.location.search).not.toContain("search=");
  });
});
