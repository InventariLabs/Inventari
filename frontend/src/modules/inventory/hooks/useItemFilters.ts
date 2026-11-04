import { useState, useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { useFilteredList } from "@/hooks/useFilteredList";

type ItemSortBy = "created_at" | "name" | "quantity" | "expiry_date";
type ItemSortOrder = "asc" | "desc";

/** The sort an address names; a part it does not name or names wrongly is absent. */
function sortFromAddress(params: URLSearchParams): {
  by?: ItemSortBy;
  order?: ItemSortOrder;
} {
  const by = params.get("sort_by");
  const order = params.get("sort_order");
  return {
    by:
      by && ["created_at", "name", "quantity", "expiry_date"].includes(by)
        ? (by as ItemSortBy)
        : undefined,
    order: order === "asc" || order === "desc" ? order : undefined,
  };
}

/**
 * Item list filters — thin wrapper over the generic `useFilteredList` factory.
 *
 * Preserves the original flat return interface so `ItemsPage.tsx` needs
 * zero changes.
 */
export function useItemFilters() {
  const [searchParams, setSearchParams] = useSearchParams();

  const f = useFilteredList(
    {
      storageFilter: { default: "", urlKey: "location_id" },
      categoryFilter: { default: "", urlKey: "category_id" },
      expiringFilter: {
        default: false,
        urlKey: "filter",
        urlValue: "expiring",
      },
      expiredFilter: { default: false, urlKey: "filter", urlValue: "expired" },
      lowStockFilter: {
        default: false,
        urlKey: "filter",
        urlValue: "low-stock",
      },
      usedUpFilter: {
        default: false,
        urlKey: "filter",
        urlValue: "used-up",
      },
      // Expired, expiring soon or running low: the records behind the
      // "needs attention" number on the dashboard and the statistics card.
      attentionFilter: {
        default: false,
        urlKey: "filter",
        urlValue: "needs-attention",
      },
    },
    // The narrowing is part of the address, so a screen opened from the list
    // and left with Back finds the list as it was, not the full one.
    {
      searchDebounceMs: 400,
      limit: 50,
      syncToUrl: true,
      urlSearchKey: "search",
    },
  );

  // The sort the address names, read at the first render so a list reopened
  // with Back asks for its order once, not for the default order first.
  const [sortBy, setSortByState] = useState<ItemSortBy>(
    () => sortFromAddress(searchParams).by ?? "created_at",
  );
  const [sortOrder, setSortOrderState] = useState<ItemSortOrder>(
    () => sortFromAddress(searchParams).order ?? "desc",
  );

  // Follow the address when it changes under the screen (Back, a link).
  useEffect(() => {
    const { by, order } = sortFromAddress(searchParams);
    if (by) setSortByState(by);
    if (order) setSortOrderState(order);
  }, [searchParams]);

  // Reset pagination when sort changes.
  //
  // Depend on the setter, not on the filter object: `useFilteredList` rebuilds
  // that object on every render, so listing it here re-ran the reset after
  // every render and the list could never leave the first page.
  const { setSkip } = f;
  useEffect(() => {
    setSkip(0);
  }, [sortBy, sortOrder, setSkip]);

  // showFilters is pure UI state — not a data filter.
  // Auto-open the filter panel when the URL sets a value that only the panel
  // can show and clear: the place picker. A chip (`filter=`) and the search
  // field already say what narrows the list, and opening the pickers for them
  // put two empty selects between a phone's reader and the first product.
  const placeFromLink = !!searchParams.get("location_id");
  const [showFilters, setShowFilters] = useState(placeFromLink);

  // …and when a place arrives after mount. Following a storage link from a row
  // narrows the list on the route it is already on, so nothing remounts: the
  // list came back shorter with every control still saying "no filters", and
  // the way back to the full list was invisible. Only the place counts here:
  // the panel holds the pickers, while the status chips sit outside it and
  // write ?filter= themselves, and so does the search — the reader's own
  // clicks must not open it.
  const hadPlaceFromLink = useRef(placeFromLink);
  useEffect(() => {
    if (placeFromLink && !hadPlaceFromLink.current) setShowFilters(true);
    hadPlaceFromLink.current = placeFromLink;
  }, [placeFromLink]);

  return {
    /** True once the reader has typed or ticked something. */
    isNarrowed: f.isNarrowed,
    /**
     * The way back from a narrowed list: search, pickers and chips as they
     * were found. The empty state offers it whenever any one of them is on,
     * so it clears every control this hook owns in one click.
     */
    clearFilters: () => {
      f.setSearchInput("");
      f.setFilter("storageFilter", "");
      f.setFilter("categoryFilter", "");
      f.setFilter("expiringFilter", false);
      f.setFilter("expiredFilter", false);
      f.setFilter("lowStockFilter", false);
      f.setFilter("usedUpFilter", false);
      f.setFilter("attentionFilter", false);
    },
    // Search
    searchInput: f.searchInput,
    setSearchInput: f.setSearchInput,
    search: f.search,
    // Filters (flat interface for backward compatibility)
    storageFilter: f.values.storageFilter as string,
    setStorageFilter: (v: string) => f.setFilter("storageFilter", v),
    categoryFilter: f.values.categoryFilter as string,
    setCategoryFilter: (v: string) => f.setFilter("categoryFilter", v),
    expiringFilter: f.values.expiringFilter as boolean,
    // The two date chips are alternatives: they combine with AND, and no
    // product is both "soon" and "past", so both on read as "No matching
    // products" next to an expired yogurt. Turning one on turns the other off.
    setExpiringFilter: (v: boolean) => {
      if (v) f.setFilter("expiredFilter", false);
      f.setFilter("expiringFilter", v);
    },
    expiredFilter: f.values.expiredFilter as boolean,
    setExpiredFilter: (v: boolean) => {
      if (v) f.setFilter("expiringFilter", false);
      f.setFilter("expiredFilter", v);
    },
    lowStockFilter: f.values.lowStockFilter as boolean,
    setLowStockFilter: (v: boolean) => f.setFilter("lowStockFilter", v),
    usedUpFilter: f.values.usedUpFilter as boolean,
    setUsedUpFilter: (v: boolean) => f.setFilter("usedUpFilter", v),
    attentionFilter: f.values.attentionFilter as boolean,
    setAttentionFilter: (v: boolean) => f.setFilter("attentionFilter", v),
    // Sorting
    sortBy,
    sortOrder,
    // The order is part of the address like the narrowing: a product opened
    // from the list and left with Back finds the rows where the reader had
    // put them, not in the default order under the same scroll offset. The
    // default order stays out of the address.
    setSort: (by: ItemSortBy, order: ItemSortOrder) => {
      setSortByState(by);
      setSortOrderState(order);
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current);
          if (by === "created_at" && order === "desc") {
            next.delete("sort_by");
            next.delete("sort_order");
          } else {
            next.set("sort_by", by);
            next.set("sort_order", order);
          }
          return next;
        },
        { replace: true },
      );
    },
    // UI state
    showFilters,
    setShowFilters,
    // Pagination
    skip: f.skip,
    setSkip: f.setSkip,
    limit: f.limit,
    setLimit: (next: number) => {
      f.setLimit(next);
      f.setSkip(0);
    },
  };
}
