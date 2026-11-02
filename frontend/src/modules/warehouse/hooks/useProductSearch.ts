import { useCallback, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  documentsApi,
  type ProductSearchResult,
} from "@/modules/warehouse/api/documents";
import { extractApiError } from "@/lib/errors";

interface UseProductSearchOptions {
  onSelect?: (product: ProductSearchResult) => void;
  /** Narrows a stock search to this location and the ones under it. */
  locationId?: string | null;
  /**
   * Answer with the stock on hand rather than the product catalogue.
   *
   * A location used to be the only way to ask for stock, so a document with
   * no location of its own — a scrap — got catalogue entries, and the line it
   * built could not be carried out.
   */
  stockOnly?: boolean;
  /**
   * Fold records nothing on a row can tell apart into one row per shelf.
   * Only honest where the executor pulls across records — set it for
   * dispatch and scrap, never for a transfer.
   */
  merge?: boolean;
}

/** How many places-it-stands hints the picker shows for a missing product. */
const ELSEWHERE_LIMIT = 5;

export function useProductSearch({
  onSelect,
  locationId,
  stockOnly = false,
  merge = false,
}: UseProductSearchOptions = {}) {
  const { t } = useTranslation("warehouse");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ProductSearchResult[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Where the product stands when the location the search is narrowed to
  // holds none of it — see ELSEWHERE_LIMIT.
  const [elsewhere, setElsewhere] = useState<ProductSearchResult[]>([]);
  // Every keystroke is its own request and the answers do not arrive in
  // order: only the last one asked may write, or a slow answer to "ba" puts
  // its list back over the one for "bar".
  const latestRequest = useRef(0);

  const search = useCallback(
    async (searchQuery: string) => {
      const request = ++latestRequest.current;
      setElsewhere([]);
      if (!searchQuery.trim()) {
        setResults([]);
        setIsLoading(false);
        return;
      }

      setIsLoading(true);
      setError(null);

      try {
        const data =
          stockOnly || locationId
            ? await documentsApi.stockSearch(
                searchQuery,
                locationId,
                undefined,
                merge,
              )
            : await documentsApi.productSearch(searchQuery);
        if (request !== latestRequest.current) return;
        setResults(data);
        if (locationId && data.length === 0) {
          // A product stocked only in another place is not "not found": the
          // picker says where it stands. A failure here costs the hint, not
          // the search.
          const found = await documentsApi
            .stockSearch(searchQuery, null, ELSEWHERE_LIMIT, merge)
            .catch(() => []);
          if (request === latestRequest.current) setElsewhere(found);
        }
      } catch (e) {
        if (request !== latestRequest.current) return;
        setError(extractApiError(e, t("form.productSearchFailed")));
        setResults([]);
      } finally {
        if (request === latestRequest.current) setIsLoading(false);
      }
    },
    [locationId, merge, stockOnly, t],
  );

  const selectResult = useCallback(
    (product: ProductSearchResult) => {
      onSelect?.(product);
      latestRequest.current++;
      setQuery("");
      setResults([]);
      setElsewhere([]);
    },
    [onSelect],
  );

  const clearSearch = useCallback(() => {
    latestRequest.current++;
    setQuery("");
    setResults([]);
    setElsewhere([]);
    setIsLoading(false);
    setError(null);
  }, []);

  return {
    query,
    setQuery,
    results,
    elsewhere,
    isLoading,
    error,
    search,
    selectResult,
    clearSearch,
  };
}
