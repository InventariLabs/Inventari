import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { useDocuments } from "@/modules/warehouse/hooks/useDocuments";
import {
  useDocumentListContributions,
  useModuleFilters,
} from "@/modules/warehouse/hooks/useDocumentContributions";
import {
  HISTORY_CHIPS,
  HISTORY_PLANNED_STATUSES,
  type HistoryChipKey,
} from "@/modules/warehouse/historyEntry";

const PAGE_SIZE = 50;

/**
 * The History list: completed documents, latest completed first, narrowed
 * by a search and by the kind of action. Work that is not done yet — drafts, documents
 * waiting for approval, planned ones — stays out of it and is one toggle
 * away, so a plan never reads as something that happened.
 */
export function useDocumentHistory() {
  const [search, setSearch] = useState("");
  const [chip, setChip] = useState<HistoryChipKey>("all");
  const [planned, setPlanned] = useState(false);
  const moduleFilters = useModuleFilters();
  const [offset, setOffset] = useState(0);
  const deferredSearch = useDeferredValue(search);

  useEffect(() => {
    setOffset(0);
  }, [deferredSearch, chip, planned, moduleFilters.active]);

  const types = HISTORY_CHIPS.find((c) => c.key === chip)?.types;
  const { data, isLoading, isError, refetch } = useDocuments({
    search: deferredSearch.trim() || undefined,
    type: types,
    status: planned ? HISTORY_PLANNED_STATUSES : "COMPLETED",
    module_filter:
      moduleFilters.active.length > 0 ? moduleFilters.active : undefined,
    limit: PAGE_SIZE,
    offset,
    // The time each row prints (`HistoryRow`): when a document was
    // completed, or for work not done yet when it was typed in. Ordered by
    // the document's date, a dispatch written last week and completed today
    // stood among last week's entries, pages behind today's.
    sort_by: planned ? "created_at" : "completed_at",
    sort_order: "desc",
  });

  const entries = useMemo(() => data?.items ?? [], [data]);
  const contributed = useDocumentListContributions(entries, moduleFilters);

  return {
    entries,
    total: data?.total ?? 0,
    isLoading,
    isError,
    refetch,
    search,
    setSearch,
    chip,
    setChip,
    planned,
    togglePlanned: () => setPlanned((p) => !p),
    // What enabled modules add: the columns some row on the page fills,
    // and their filter chips.
    moduleColumns: contributed.columns,
    moduleFilters: contributed.filters,
    isNarrowed:
      search.trim() !== "" || chip !== "all" || moduleFilters.active.length > 0,
    clearFilters: () => {
      setSearch("");
      setChip("all");
      moduleFilters.clear();
    },
    skip: offset,
    limit: PAGE_SIZE,
    onPrev: () => setOffset((o) => Math.max(o - PAGE_SIZE, 0)),
    onNext: () =>
      setOffset((o) =>
        o + PAGE_SIZE < (data?.total ?? 0) ? o + PAGE_SIZE : o,
      ),
    onPageChange: (page: number) =>
      setOffset(Math.max(0, (page - 1) * PAGE_SIZE)),
  };
}
