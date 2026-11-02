import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useProductSearch } from "./useProductSearch";
import { documentsApi } from "@/modules/warehouse/api/documents";

vi.mock("@/modules/warehouse/api/documents", () => ({
  documentsApi: {
    productSearch: vi.fn(async () => []),
    stockSearch: vi.fn(async () => []),
  },
}));

describe("useProductSearch", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("searches the catalogue when no location scopes it", async () => {
    const { result } = renderHook(() => useProductSearch());
    await act(async () => {
      await result.current.search("bolt");
    });
    expect(documentsApi.productSearch).toHaveBeenCalledWith("bolt");
    expect(documentsApi.stockSearch).not.toHaveBeenCalled();
  });

  it("searches the stock in the location it was given", async () => {
    // A dispatch line has to name an item, and only the stock search knows one.
    const { result } = renderHook(() =>
      useProductSearch({ locationId: "loc-1" }),
    );
    await act(async () => {
      await result.current.search("bolt");
    });
    expect(documentsApi.stockSearch).toHaveBeenCalledWith(
      "bolt",
      "loc-1",
      undefined,
      false,
    );
    expect(documentsApi.productSearch).not.toHaveBeenCalled();
  });

  it("searches the stock with no location when the document has none", async () => {
    // A scrap names no shelf of its own — the record it names says where the
    // goods stand. Asking the catalogue instead handed back entries the
    // executor could do nothing with, and the document closed as done having
    // moved nothing.
    const { result } = renderHook(() => useProductSearch({ stockOnly: true }));
    await act(async () => {
      await result.current.search("honey");
    });
    expect(documentsApi.stockSearch).toHaveBeenCalledWith(
      "honey",
      undefined,
      undefined,
      false,
    );
    expect(documentsApi.productSearch).not.toHaveBeenCalled();
  });

  it("keeps an empty query away from the network", async () => {
    const { result } = renderHook(() =>
      useProductSearch({ locationId: "loc-1" }),
    );
    await act(async () => {
      await result.current.search("   ");
    });
    await waitFor(() => {
      expect(documentsApi.stockSearch).not.toHaveBeenCalled();
    });
  });
});

describe("useProductSearch — the merge flag rides only where it was set", () => {
  it("asks the endpoint to fold identical records for a dispatch", async () => {
    const { result } = renderHook(() =>
      useProductSearch({ stockOnly: true, merge: true }),
    );
    await act(async () => {
      await result.current.search("bolt");
    });
    expect(documentsApi.stockSearch).toHaveBeenCalledWith(
      "bolt",
      undefined,
      undefined,
      true,
    );
  });

  it("keeps the records one by one when the caller does not merge", async () => {
    const { result } = renderHook(() =>
      useProductSearch({ stockOnly: true, locationId: "loc-1" }),
    );
    await act(async () => {
      await result.current.search("bolt");
    });
    expect(documentsApi.stockSearch).toHaveBeenCalledWith(
      "bolt",
      "loc-1",
      undefined,
      false,
    );
  });

  describe("a search that finds nothing in the source location", () => {
    const gouda = { name: "Gouda Cheese", location_name: "Fridge B" };

    it("looks for the product elsewhere and offers what it finds", async () => {
      // Stock stood in Fridge B, the transfer's source was Dry Goods: the
      // scoped search answered with nothing and the picker said so, without
      // a word about where the product was.
      vi.mocked(documentsApi.stockSearch)
        .mockResolvedValueOnce([])
        .mockResolvedValueOnce([gouda] as never);
      const { result } = renderHook(() =>
        useProductSearch({ locationId: "dry-goods", stockOnly: true }),
      );
      await act(async () => {
        await result.current.search("Gouda");
      });
      expect(documentsApi.stockSearch).toHaveBeenNthCalledWith(
        2,
        "Gouda",
        null,
        5,
        false,
      );
      expect(result.current.results).toEqual([]);
      expect(result.current.elsewhere).toEqual([gouda]);
    });

    it("does not look elsewhere when the source location has a match", async () => {
      vi.mocked(documentsApi.stockSearch).mockResolvedValueOnce([
        gouda,
      ] as never);
      const { result } = renderHook(() =>
        useProductSearch({ locationId: "dry-goods", stockOnly: true }),
      );
      await act(async () => {
        await result.current.search("Gouda");
      });
      expect(documentsApi.stockSearch).toHaveBeenCalledTimes(1);
      expect(result.current.elsewhere).toEqual([]);
    });

    it("does not look elsewhere when no location narrows the search", async () => {
      const { result } = renderHook(() =>
        useProductSearch({ stockOnly: true }),
      );
      await act(async () => {
        await result.current.search("Gouda");
      });
      expect(documentsApi.stockSearch).toHaveBeenCalledTimes(1);
    });

    it("forgets what it found when the search is cleared", async () => {
      vi.mocked(documentsApi.stockSearch)
        .mockResolvedValueOnce([])
        .mockResolvedValueOnce([gouda] as never);
      const { result } = renderHook(() =>
        useProductSearch({ locationId: "dry-goods" }),
      );
      await act(async () => {
        await result.current.search("Gouda");
      });
      act(() => result.current.clearSearch());
      expect(result.current.elsewhere).toEqual([]);
    });
  });

  it("keeps the answer to the last keystroke when an earlier answer arrives late", async () => {
    // The reported stall: the picker stopped following what was typed. Each
    // keystroke is its own request, and the slow answer to "ba" used to land
    // after the answer to "bar" and put the older list back.
    let answerFirst: (rows: never[]) => void = () => {};
    vi.mocked(documentsApi.productSearch)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            answerFirst = resolve as (rows: never[]) => void;
          }),
      )
      .mockResolvedValueOnce([{ name: "Bar" }] as never);
    const { result } = renderHook(() => useProductSearch());
    let first: Promise<void> = Promise.resolve();
    act(() => {
      first = result.current.search("ba");
    });
    await act(async () => {
      await result.current.search("bar");
    });
    await act(async () => {
      answerFirst([{ name: "Bat" }] as never[]);
      await first;
    });
    expect(result.current.results).toEqual([{ name: "Bar" }]);
    expect(result.current.isLoading).toBe(false);
  });
});
