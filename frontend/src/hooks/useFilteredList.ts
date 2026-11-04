import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { useDebounce } from "@/hooks/useDebounce";

/**
 * Whether a list screen should render its narrowing tools.
 *
 * An empty list means two different things — "there is nothing here yet" and
 * "your filter found nothing" — and a screen that cannot tell them apart
 * offers eight ways to sort nothing. The tools come back with the first row,
 * and whenever the reader has narrowed the list themselves and needs a way to
 * widen it again.
 *
 * Pages using `useFilteredList` pass its `isNarrowed`; pages holding their own
 * filter state compute the same question locally. Either way the rule itself
 * lives here once.
 */
export function showListControls(state: {
  isLoading: boolean;
  total: number;
  isNarrowed: boolean;
}): boolean {
  return state.isLoading || state.total > 0 || state.isNarrowed;
}

/**
 * Configuration for a single filter managed by useFilteredList.
 */
interface FilterConfig<V> {
  /** Default value when no URL param is present. */
  default: V;
  /** URL search-param key. Omit to skip URL sync. */
  urlKey?: string;
  /**
   * For boolean filters that share a `urlKey` (e.g. `?filter=expiring` vs
   * `?filter=expired`), set this to the param value that should flip the
   * boolean to `true`.  When omitted and the default is boolean, any
   * non-empty param value sets the boolean to `true`.  Several such filters
   * can be on at once: the param then carries their values comma-separated
   * (`?filter=expired,low-stock`), so each filter keeps its own place in it.
   */
  urlValue?: string;
}

/**
 * Configuration object for useFilteredList.
 * Each key becomes a filter; the value is its config.
 */
type FilterDefinitions = Record<
  string,
  FilterConfig<string | boolean | number>
>;

type FilterEntries = [string, FilterConfig<string | boolean | number>][];

/** Read one filter's value out of the URL, or its default when absent. */
function valueFromParam(
  cfg: FilterConfig<string | boolean | number>,
  param: string | null,
): string | boolean | number {
  if (param === null) return cfg.default;
  if (typeof cfg.default === "boolean") {
    return cfg.urlValue
      ? param.split(",").includes(cfg.urlValue)
      : param.length > 0;
  }
  if (typeof cfg.default === "number") {
    const n = Number(param);
    return isNaN(n) ? cfg.default : n;
  }
  return param;
}

function readFilterState(
  entries: FilterEntries,
  searchParams: URLSearchParams,
): Record<string, string | boolean | number> {
  const init: Record<string, string | boolean | number> = {};
  for (const [key, cfg] of entries) {
    init[key] = cfg.urlKey
      ? valueFromParam(cfg, searchParams.get(cfg.urlKey))
      : cfg.default;
  }
  return init;
}

/**
 * Generic list filter hook factory.
 *
 * Manages debounced search, arbitrary filter state, and server-side
 * pagination.  Optionally syncs filter values to URL search-params.
 *
 * @example
 * const f = useFilteredList({
 *   storage:  { default: "", urlKey: "location_id" },
 *   category: { default: "" },
 *   expiring: { default: false, urlKey: "filter" },
 * }, { searchDebounceMs: 400, limit: 100 });
 *
 * // f.values.storage, f.set("storage", "abc"), f.search, f.skip …
 */
export function useFilteredList<T extends FilterDefinitions>(
  filterDefs: T,
  options?: {
    searchDebounceMs?: number;
    limit?: number;
    /** Persist configured filters when the reader changes them. */
    syncToUrl?: boolean;
    /**
     * Keep the typed search in this URL param too, and start from it. A
     * screen opened from the list and left with Back then finds the list as
     * the reader narrowed it.
     */
    urlSearchKey?: string;
  },
) {
  const {
    searchDebounceMs = 400,
    limit: initialLimit = 100,
    syncToUrl = false,
    urlSearchKey,
  } = options ?? {};
  const [searchParams, setSearchParams] = useSearchParams();

  // ── Search ──
  const [searchInput, setSearchState] = useState(
    () => (urlSearchKey && searchParams.get(urlSearchKey)) || "",
  );
  const search = useDebounce(searchInput, searchDebounceMs);

  // ── Filter state (initialised from URL if configured) ──
  const entries = useMemo(
    () => Object.entries(filterDefs) as FilterEntries,
    [filterDefs],
  );

  const [filterState, setFilterState] = useState<
    Record<string, string | boolean | number>
  >(() => readFilterState(entries, searchParams));

  /**
   * Keep the filters answering to the URL after mount, not only at it.
   *
   * A row of the product list links to `?location_id=…` on the route it is
   * already on. React Router swaps the search string without unmounting, so
   * a state initialiser never runs again: the link registered as a click and
   * changed nothing, which reads as a dead link. Entering the same address
   * from outside filtered correctly, which is what made it hard to see.
   *
   * Only the params that actually changed are re-applied. A filter the reader
   * set by hand carries no param, so following a link does not silently
   * discard it.
   */
  const urlKeys = useMemo(
    () =>
      entries
        .map(([, cfg]) => cfg.urlKey)
        .filter((k): k is string => Boolean(k)),
    [entries],
  );
  const urlSignature = urlKeys
    .map((k) => `${k}=${searchParams.get(k) ?? ""}`)
    .join("&");
  const appliedParamsRef = useRef<Record<string, string | null>>(
    Object.fromEntries(urlKeys.map((k) => [k, searchParams.get(k)])),
  );

  useEffect(() => {
    const changed = new Set<string>();
    const next: Record<string, string | null> = {};
    for (const key of urlKeys) {
      next[key] = searchParams.get(key);
      if (next[key] !== appliedParamsRef.current[key]) changed.add(key);
    }
    if (changed.size === 0) return;
    appliedParamsRef.current = next;

    setFilterState((current) => {
      const updated = { ...current };
      for (const [key, cfg] of entries) {
        if (!cfg.urlKey || !changed.has(cfg.urlKey)) continue;
        updated[key] = valueFromParam(cfg, next[cfg.urlKey]);
      }
      return updated;
    });
    // `urlSignature` is the stable read of every watched param; `searchParams`
    // itself is a fresh object on every render and would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlSignature]);

  // Each write edits "the address as rendered", and the router commits an
  // address in a transition: several controls cleared in one go, or a second
  // chip tapped while a busy phone is still rendering the first, would each
  // start from the same old address and the last write would undo the others.
  // So a write builds on the writes the screen has not caught up with yet.
  // They are forgotten once it shows the last of them, or an address that is
  // none of them: somebody else navigated, and that address wins.
  const unrendered = useRef<string[]>([]);
  const rendered = searchParams.toString();
  useEffect(() => {
    const writes = unrendered.current;
    const stillToCome = writes.includes(rendered) && writes.at(-1) !== rendered;
    if (!stillToCome) unrendered.current = [];
  }, [rendered]);
  const writeParams = useCallback(
    (edit: (next: URLSearchParams) => void) => {
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(
            unrendered.current.at(-1) ?? current,
          );
          edit(next);
          unrendered.current.push(next.toString());
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const setSearchInput = useCallback(
    (value: string) => {
      setSearchState(value);
      if (!syncToUrl || !urlSearchKey) return;
      writeParams((next) => {
        if (value) next.set(urlSearchKey, value);
        else next.delete(urlSearchKey);
      });
    },
    [syncToUrl, urlSearchKey, writeParams],
  );

  /**
   * Update a single filter value by key.
   */
  const setFilter = useCallback(
    (key: string, value: string | boolean | number) => {
      setFilterState((prev) => ({ ...prev, [key]: value }));
      const cfg = filterDefs[key];
      const urlKey = cfg?.urlKey;
      if (!syncToUrl || !urlKey) return;
      writeParams((next) => {
        if (cfg.urlValue && typeof value === "boolean") {
          // Filters sharing this param each own one value in its list.
          const held = (next.get(urlKey) ?? "").split(",").filter(Boolean);
          const rest = held.filter((v) => v !== cfg.urlValue);
          const updated = value ? [...rest, cfg.urlValue] : rest;
          if (updated.length > 0) next.set(urlKey, updated.join(","));
          else next.delete(urlKey);
        } else if (value === cfg.default) {
          next.delete(urlKey);
        } else {
          next.set(urlKey, String(value));
        }
      });
    },
    [filterDefs, syncToUrl, writeParams],
  );

  // ── Pagination ──
  const [skip, setSkip] = useState(0);
  const [limit, setLimit] = useState(initialLimit);

  const onPrev = useCallback(
    () => setSkip((s) => Math.max(s - limit, 0)),
    [limit],
  );
  const onNext = useCallback(() => setSkip((s) => s + limit), [limit]);
  const resetPagination = useCallback(() => setSkip(0), []);

  // Reset pagination when filters change (skip initial mount)
  const mountedRef = useRef(false);
  useEffect(() => {
    if (!mountedRef.current) {
      mountedRef.current = true;
      return;
    }
    setSkip(0);
  }, [filterState]);

  useEffect(() => {
    setSkip(0);
  }, [search]);

  /**
   * Whether the reader has narrowed the list.
   *
   * An empty list means two different things — "there is nothing here yet"
   * and "your filter found nothing" — and a screen that cannot tell them
   * apart offers narrowing tools over zero rows and calls the result "not
   * found".
   */
  const isNarrowed =
    search.trim().length > 0 ||
    Object.entries(filterState).some(
      ([key, value]) => value !== filterDefs[key]?.default,
    );

  return {
    isNarrowed,
    search,
    searchInput,
    setSearchInput,
    skip,
    setSkip,
    limit,
    setLimit,
    onPrev,
    onNext,
    resetPagination,
    /** Current values for all defined filters. */
    values: filterState as {
      [K in keyof T]: T[K]["default"];
    },
    /** Update a single filter value. */
    setFilter,
  };
}
