import { useState, useEffect, useDeferredValue, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useDocuments } from "@/modules/warehouse/hooks/useDocuments";
import {
  useDocumentListContributions,
  useModuleFilters,
} from "@/modules/warehouse/hooks/useDocumentContributions";
import {
  DOCUMENT_TYPES,
  type DocumentDiscrepancyCode,
  type DocumentStatus,
  type DocumentType,
} from "@/modules/warehouse/types";

export type DocumentTypeFilter = "ALL" | DocumentType;
export type DocumentStatusFilter = DocumentStatus | "ALL";
export type DocumentDiscrepancyFilter = DocumentDiscrepancyCode | "ALL";
export type DocumentSortBy = "document_date" | "number" | "type" | "status";
export type DocumentSortOrder = "asc" | "desc";

interface UseDocumentsListOptions {
  /** Fixed page size. Omit to let the width decide the starting value. */
  limit?: number;
}

const STATUSES: readonly DocumentStatus[] = [
  "DRAFT",
  "PENDING_APPROVAL",
  "CONFIRMED",
  "COMPLETED",
  "CANCELLED",
];

/** The filters that live in the URL — and that only this list reads. */
export const FILTER_PARAMS = [
  "type",
  "status",
  "date_from",
  "date_to",
  "partner_id",
] as const;
type UrlFilter = (typeof FILTER_PARAMS)[number];

/** Rows per page: a phone cannot carry the desktop page in one scroll. */
const DESKTOP_PAGE_SIZE = 50;
const NARROW_PAGE_SIZE = 20;

export function useDocumentsList(options: UseDocumentsListOptions = {}) {
  // The width picks the *starting* page size only. A later resize must not
  // reset the size or the page the user is on, and an explicit choice wins
  // over the responsive default — so this is an initial value, not an effect.
  const isDesktop = useMediaQuery("(min-width: 1024px)");
  const [limit, setLimit] = useState(
    () => options.limit ?? (isDesktop ? DESKTOP_PAGE_SIZE : NARROW_PAGE_SIZE),
  );
  const [discrepancyFilter, setDiscrepancyFilter] =
    useState<DocumentDiscrepancyFilter>("ALL");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<DocumentSortBy>("document_date");
  const [sortOrder, setSortOrder] = useState<DocumentSortOrder>("desc");
  const [offset, setOffset] = useState(0);
  const moduleFilters = useModuleFilters();
  // Defer the search sent to the server so typing stays responsive and we
  // do not fire a list request per keystroke (same pattern as
  // PurchaseOrdersPage).
  const deferredSearch = useDeferredValue(search);
  // The filters a person sets again on every visit — type, status and the
  // date range — live in the URL and are read from it on every render, so
  // they survive a reload and can be shared or bookmarked, and the screen
  // follows the address when a link swaps the search string under an open
  // list (a state copy seeded once would drift from it). The partner a card
  // links here with is read the same way: a link that lands on an unfiltered
  // list is worse than no link.
  const [searchParams, setSearchParams] = useSearchParams();
  const partnerId = searchParams.get("partner_id");
  const typeParam = searchParams.get("type") as DocumentType;
  const filterTypes: readonly DocumentType[] = DOCUMENT_TYPES;
  const typeFilter: DocumentTypeFilter = filterTypes.includes(typeParam)
    ? typeParam
    : "ALL";
  const statusParam = searchParams.get("status") as DocumentStatus;
  const statusFilter: DocumentStatusFilter = STATUSES.includes(statusParam)
    ? statusParam
    : "ALL";
  const dateFrom = searchParams.get("date_from") ?? "";
  const dateTo = searchParams.get("date_to") ?? "";

  /** Set or drop (empty / "ALL") URL filters, keeping the rest. */
  const writeParams = (values: Partial<Record<UrlFilter, string>>) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [key, value] of Object.entries(values)) {
          if (value && value !== "ALL") next.set(key, value);
          else next.delete(key);
        }
        return next;
      },
      { replace: true },
    );
  };
  const setTypeFilter = (value: DocumentTypeFilter) =>
    writeParams({ type: value });
  const setStatusFilter = (value: DocumentStatusFilter) =>
    writeParams({ status: value });
  const setDateFrom = (value: string) => writeParams({ date_from: value });
  const setDateTo = (value: string) => writeParams({ date_to: value });
  const clearPartnerFilter = () => writeParams({ partner_id: "" });

  // Reset to page 1 when filters or sorting change
  useEffect(() => {
    setOffset(0);
  }, [
    deferredSearch,
    typeFilter,
    statusFilter,
    discrepancyFilter,
    dateFrom,
    dateTo,
    sortBy,
    sortOrder,
    partnerId,
    moduleFilters.active,
  ]);

  const { data, isLoading, isError, refetch } = useDocuments({
    partner_id: partnerId ?? undefined,
    search: deferredSearch || undefined,
    type: typeFilter === "ALL" ? undefined : typeFilter,
    status: statusFilter === "ALL" ? undefined : statusFilter,
    discrepancy_code:
      discrepancyFilter === "ALL" ? undefined : discrepancyFilter,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    module_filter:
      moduleFilters.active.length > 0 ? moduleFilters.active : undefined,
    limit,
    offset,
    sort_by: sortBy,
    sort_order: sortOrder,
  });

  const total = data?.total ?? 0;
  const documents = useMemo(() => data?.items ?? [], [data]);
  const contributed = useDocumentListContributions(documents, moduleFilters);

  /** True when what the reader sees is a narrowed list, not the whole shelf. */
  const isNarrowed =
    Boolean(search) ||
    Boolean(partnerId) ||
    Boolean(dateFrom) ||
    Boolean(dateTo) ||
    typeFilter !== "ALL" ||
    statusFilter !== "ALL" ||
    discrepancyFilter !== "ALL" ||
    moduleFilters.active.length > 0;

  /**
   * Put every filter back to "everything".
   *
   * A list narrowed to nothing has to offer the way out of the narrowing —
   * clearing them one control at a time means finding all the controls
   * first, and one of them is a banner that lives outside the filter bar.
   */
  const clearFilters = () => {
    setSearch("");
    setDiscrepancyFilter("ALL");
    moduleFilters.clear();
    writeParams(
      Object.fromEntries(FILTER_PARAMS.map((key) => [key, ""])) as Record<
        UrlFilter,
        string
      >,
    );
  };

  const onPrev = () => setOffset((o) => Math.max(o - limit, 0));
  const onNext = () => setOffset((o) => (o + limit < total ? o + limit : o));
  // Page numbers are 1-based in the shared pager.
  const onPageChange = (page: number) =>
    setOffset(Math.max(0, (page - 1) * limit));
  const onLimitChange = (next: number) => {
    setLimit(next);
    setOffset(0);
  };

  return {
    documents,
    total,
    isLoading,
    // Without these the page could only say "no documents" when the request
    // failed — the same screen for "the list is empty" and "we could not
    // load it", and no way to try again.
    isError,
    refetch,
    partnerId,
    clearPartnerFilter,
    search,
    typeFilter,
    statusFilter,
    discrepancyFilter,
    dateFrom,
    dateTo,
    // What enabled modules add: the columns some row on the page fills, and
    // their filters, which the server answers.
    moduleColumns: contributed.columns,
    moduleFilters: contributed.filters,
    isNarrowed,
    sortBy,
    sortOrder,
    skip: offset,
    limit,
    setSearch,
    setTypeFilter,
    setStatusFilter,
    setDiscrepancyFilter,
    setDateFrom,
    setDateTo,
    clearFilters,
    setSortBy,
    setSortOrder,
    onPrev,
    onNext,
    onPageChange,
    onLimitChange,
  };
}
