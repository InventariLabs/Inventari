import { useState, useMemo, useCallback, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useEquipmentAssets } from "@/modules/equipment/hooks/useEquipmentAssets";
import {
  useBulkRetireEquipment,
  useBulkArchiveEquipment,
  useBulkReturnEquipment,
  useBulkPurgeEquipment,
  useRestoreEquipment,
  useBulkEditAssets,
  useRetireMatchingAssets,
  useArchiveMatchingAssets,
} from "@/modules/equipment/hooks/useEquipment";
import { ReadableError, extractApiError } from "@/lib/errors";
import { itemsApi } from "@/lib/api/items";
import { labelsApi } from "@/lib/api/labels";
import { downloadBlob } from "@/utils/helpers";
import { getTodayFilename } from "@/utils/formatters";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { queryKeys } from "@/hooks/queries/keys";
import { useKeysetPaging } from "@/module-sdk";
import { getEquipmentMeta } from "@/modules/equipment/components/assetUtils";
import {
  bulkReturnPayload,
  bulkReturnedText,
  type BulkReturnChoice,
} from "@/modules/equipment/components/checkinConditions";
import {
  bulkFailureDetail,
  type BulkRowError,
} from "@/modules/equipment/components/bulkOutcome";
import type {
  AssetFilter,
  BulkPurgeError,
  EquipmentSortDir,
  EquipmentSortKey,
} from "@/modules/equipment/api/equipment_assets";

const ASSET_STATUSES = ["AVAILABLE", "DEPLOYED", "MAINTENANCE"] as const;
type AssetStatus = (typeof ASSET_STATUSES)[number];
type ListTab = "active" | "archived";

const PAGE_SIZE = 50;

export { ASSET_STATUSES };

/**
 * The four filters the address carries, the search phrase and the tab the list is on are read
 * from it on every render, not copied into state at mount. The module's own
 * navigation ("Assets" in the module bar, a location card's link) replaces
 * the search string without unmounting this page: a mount-time copy kept the
 * old narrowing — chip, rows, dropdown — behind an address that no longer
 * had it. The handlers write the address; this render follows.
 */
function useAssetListAddress() {
  const [searchParams, setSearchParams] = useSearchParams();

  const statusFilter = (searchParams.get("status") as AssetStatus | null) ?? "";
  const checkedOut =
    searchParams.get("checked_out") === "1" ||
    searchParams.get("checked_out") === "true";
  const locationFilter = searchParams.get("location") ?? "";
  const categoryFilter = searchParams.get("category") ?? "";
  // Same rule for the tab: it was readable from the address and written
  // nowhere, so a copied archive address opened the active list.
  const listTab: ListTab =
    searchParams.get("tab") === "archived" ? "archived" : "active";

  // The status segment is one control for every status-like narrowing, so a
  // pick drops the address's checked-out flag along with the old status:
  // "All" cleared only `status` and left a list that was still narrowed.
  function handleStatusFilter(status: AssetStatus | "") {
    setSearchParams(
      (prev) => {
        if (status) prev.set("status", status);
        else prev.delete("status");
        prev.delete("checked_out");
        return prev;
      },
      { replace: true },
    );
  }

  // "checked out" = assets with an open assignment. Driven by
  // the dashboard tile link /?checked_out=1 and cleared like other filters.
  // The location filter speaks through the URL like status and checked-out
  // do: /equipment/locations links here with ?location=<id>, and a refresh
  // or a shared link has to land on the same narrowed list. The dropdown
  // writes the param back, so the address never drifts from the view.
  function handleLocationFilter(value: string) {
    setSearchParams(
      (prev) => {
        if (value) prev.set("location", value);
        else prev.delete("location");
        return prev;
      },
      { replace: true },
    );
  }

  function handleCheckedOutChange(value: boolean) {
    setSearchParams(
      (prev) => {
        if (value) prev.set("checked_out", "1");
        else prev.delete("checked_out");
        return prev;
      },
      { replace: true },
    );
  }

  // The category filter arrives the same way the location one does — the
  // dashboard's composition card links here with ?category=<id> — so it
  // answers the address on every render like the other three.
  const setCategoryFilter = useCallback(
    (value: string) => {
      setSearchParams(
        (prev) => {
          if (value) prev.set("category", value);
          else prev.delete("category");
          return prev;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  // One navigation for several params. Separate setSearchParams calls in the
  // same tick all start from the same snapshot, so the last one wins — a
  // "Clear" naming four filters left the other three behind in the address.
  const clearFilterParams = useCallback(
    (keys: readonly string[]) => {
      setSearchParams(
        (prev) => {
          for (const key of keys) prev.delete(key);
          return prev;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const clearAllFilters = useCallback(
    () => clearFilterParams(["status", "checked_out", "location", "category"]),
    [clearFilterParams],
  );
  // The empty state's "Clear" undoes everything that narrowed the list,
  // the phrase included, in the one navigation the note above asks for.
  const clearFiltersAndSearch = useCallback(
    () =>
      clearFilterParams(["status", "checked_out", "location", "category", "q"]),
    [clearFilterParams],
  );
  const clearLocationAndCategory = useCallback(
    () => clearFilterParams(["location", "category"]),
    [clearFilterParams],
  );

  const writeListTab = useCallback(
    (tab: ListTab) => {
      setSearchParams(
        (prev) => {
          if (tab === "archived") prev.set("tab", "archived");
          else prev.delete("tab");
          return prev;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  // The Archive tab answers a different question — what the module archived
  // — and narrows by none of the four. A param it cannot honour is dropped
  // from the address however that tab is reached, the tab click or a typed
  // ?tab=archived: a narrowing the screen does not apply must not survive in
  // the address that gets copied.
  useEffect(() => {
    if (listTab !== "archived") return;
    const narrowedByAddress =
      searchParams.get("status") ||
      searchParams.get("checked_out") ||
      searchParams.get("location") ||
      searchParams.get("category");
    if (!narrowedByAddress) return;
    clearAllFilters();
  }, [listTab, searchParams, clearAllFilters]);

  return {
    statusFilter,
    handleStatusFilter,
    checkedOut,
    handleCheckedOutChange,
    locationFilter,
    handleLocationFilter,
    categoryFilter,
    setCategoryFilter,
    clearFiltersAndSearch,
    clearLocationAndCategory,
    listTab,
    writeListTab,
  };
}

/**
 * The search phrase lives in the address too (`?q=`): a reload or a shared
 * link lands on the same narrowed list instead of the whole register, and
 * both tabs read the one phrase.
 */
function useSearchPhrase() {
  const [searchParams, setSearchParams] = useSearchParams();
  const setSearch = useCallback(
    (value: string) => {
      setSearchParams(
        (prev) => {
          if (value) prev.set("q", value);
          else prev.delete("q");
          return prev;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );
  return [searchParams.get("q") ?? "", setSearch] as const;
}

/**
 * The archive as the toolbar's search box narrows it. The phrase counts only
 * while the archived tab is on screen: typed over the active list it belongs
 * to that list, and re-asking the archive on every keystroke would be work
 * for a tab nobody is reading. Coming back with a phrase still in the box
 * narrows the archive then. The archive pages by the last row seen, so a new
 * phrase — or coming back to the tab — starts it from its first page: a
 * position in one answer means nothing in another.
 */
function useArchivedListing(listTab: ListTab, search: string) {
  const archivedSearch = listTab === "archived" ? search : "";
  const paging = useKeysetPaging({ listTab, archivedSearch });

  const { data, isLoading, isError, isPlaceholderData, refetch } = useQuery({
    queryKey: [
      ...queryKeys.equipment.assets.list({}),
      "archived",
      archivedSearch,
      paging.cursor ?? null,
    ],
    queryFn: async () => {
      return itemsApi.getArchived({
        module_scope: "equipment",
        search: archivedSearch || undefined,
        cursor: paging.cursor,
        limit: PAGE_SIZE,
      });
    },
    placeholderData: keepPreviousData,
  });

  const { goNext } = paging;
  const nextCursor = data?.next_cursor;
  // The cursor on screen belongs to the page it came with; while the next
  // page loads the old rows are still shown, and their cursor must not be
  // taken for the new page's.
  const onNext = useCallback(() => {
    if (!isPlaceholderData) goNext(nextCursor);
  }, [isPlaceholderData, goNext, nextCursor]);

  return {
    skip: paging.page * PAGE_SIZE,
    hasNext: Boolean(nextCursor),
    archivedSearch,
    data,
    isLoading,
    isError,
    refetch,
    onPrev: paging.goPrev,
    onNext,
  };
}

export function useAssetListActions() {
  const { t } = useTranslation("equipment");
  const {
    statusFilter,
    handleStatusFilter,
    checkedOut,
    handleCheckedOutChange,
    locationFilter,
    handleLocationFilter,
    categoryFilter,
    setCategoryFilter,
    clearFiltersAndSearch,
    clearLocationAndCategory,
    listTab,
    writeListTab,
  } = useAssetListAddress();
  const [search, setSearch] = useSearchPhrase();
  const [skip, setSkip] = useState(0);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  // The selection is a set of ids from one page. This flag widens it to
  // "everything the filters match": the server runs retire/archive over the
  // filter itself, so the eleven assets on the next page are no longer out
  // of reach. Any touch of a checkbox narrows it back to the page.
  const [allMatching, setAllMatching] = useState(false);
  const [showBulkRetireConfirm, setShowBulkRetireConfirm] = useState(false);
  const [showBulkArchiveConfirm, setShowBulkArchiveConfirm] = useState(false);
  const [showBulkReturn, setShowBulkReturn] = useState(false);
  const [showBulkPurgeConfirm, setShowBulkPurgeConfirm] = useState(false);
  const [restoreTarget, setRestoreTarget] = useState<string | null>(null);
  const [purgeTarget, setPurgeTarget] = useState<string | null>(null);
  const [bulkEditAction, setBulkEditAction] = useState<
    "change_status" | "change_location" | "assign_to" | null
  >(null);

  // server-side sorting (8a). Default mirrors the historical list
  // order (created_at desc).
  const [sort, setSort] = useState<EquipmentSortKey>("created_at");
  const [sortDir, setSortDir] = useState<EquipmentSortDir>("desc");

  // What the list shows and what a whole-set action covers are one scope.
  const scope = useMemo<AssetFilter>(
    () => ({
      search: search || undefined,
      category_id: categoryFilter || undefined,
      location_id: locationFilter || undefined,
      status: statusFilter || undefined,
      checked_out: checkedOut,
    }),
    [search, categoryFilter, locationFilter, statusFilter, checkedOut],
  );

  const { data, isLoading, isError, refetch } = useEquipmentAssets({
    ...scope,
    checked_out: checkedOut || undefined,
    sort,
    sort_dir: sortDir,
    offset: skip,
    limit: PAGE_SIZE,
  });

  // Reset to the first page whenever any filter changes. The selection goes
  // with it: ids a new result set no longer shows are the stale-selection
  // lie behind bulk actions aimed at rows the reader cannot see.
  useEffect(() => {
    setSkip(0);
    setSelectedIds(new Set());
    setAllMatching(false);
  }, [
    search,
    categoryFilter,
    locationFilter,
    statusFilter,
    checkedOut,
    sort,
    sortDir,
  ]);

  const handleSortChange = useCallback((key: EquipmentSortKey) => {
    setSort((prev) => {
      if (prev === key) {
        setSortDir((dir) => (dir === "asc" ? "desc" : "asc"));
        return prev;
      }
      setSortDir("asc");
      return key;
    });
  }, []);

  // Explicit sort for the dropdown (8c): table headers toggle, the select
  // sets both parts at once.
  const applySort = useCallback(
    (key: EquipmentSortKey, dir: EquipmentSortDir) => {
      setSort(key);
      setSortDir(dir);
    },
    [],
  );

  const onPrev = useCallback(
    () => setSkip((s) => Math.max(0, s - PAGE_SIZE)),
    [],
  );
  const onNext = useCallback(() => {
    const total = data?.total ?? 0;
    if (total === 0) {
      return;
    }
    if (skip + PAGE_SIZE < total) {
      setSkip(skip + PAGE_SIZE);
    }
  }, [skip, data?.total]);
  const resetPagination = useCallback(() => setSkip(0), []);

  const {
    skip: archivedSkip,
    hasNext: archivedHasNext,
    archivedSearch,
    data: archivedItems,
    isLoading: archivedLoading,
    isError: archivedError,
    refetch: refetchArchived,
    onPrev: onArchivedPrev,
    onNext: onArchivedNext,
  } = useArchivedListing(listTab, search);

  const bulkRetireMutation = useBulkRetireEquipment();
  const bulkArchiveMutation = useBulkArchiveEquipment();
  const bulkReturnMutation = useBulkReturnEquipment();
  const bulkPurgeMutation = useBulkPurgeEquipment();
  const restoreMutation = useRestoreEquipment();
  const bulkEditMutation = useBulkEditAssets();
  const retireMatchingMutation = useRetireMatchingAssets();
  const archiveMatchingMutation = useArchiveMatchingAssets();

  // status / checked-out filters are applied server-side by the
  // module endpoint — no client-side slicing over a single page.
  // Memoised because the selection helpers below derive from it: a fresh []
  // on every render would rebuild them on every render too.
  const items = useMemo(() => data?.items ?? [], [data]);

  const equipmentArchived = useMemo(
    () => archivedItems?.items ?? [],
    [archivedItems],
  );
  const archivedTotal = archivedItems?.total ?? 0;

  // Batch endpoints report failures by item id; the reader knows assets by
  // name. Both lists feed the map because purge and restore act on archived
  // rows while the rest act on live ones.
  const nameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const asset of [...items, ...equipmentArchived]) {
      map.set(asset.id, asset.name);
    }
    return map;
  }, [items, equipmentArchived]);

  // "1 udanych, 1 błędów": one flat string cannot inflect two numbers, so
  // the two tallies are two counted sentences, joined here.
  const bulkOutcomeText = useCallback(
    (done: number, errors: number) =>
      `${t("list.bulk_done", { count: done })}, ${t("list.bulk_failed", {
        count: errors,
      })}`,
    [t],
  );

  const failureDetail = useCallback(
    (errors: BulkRowError[]) =>
      bulkFailureDetail(errors, nameById, (count) =>
        t("list.bulk_failed_more", { count }),
      ),
    [nameById, t],
  );

  // Returning means closing an open assignment, so only assets that are out
  // can be returned. The selection is not filtered for the reader — the modal
  // says how many of the selected rows the operation will touch.
  const returnableIds = useMemo(
    () =>
      items
        .filter((i) => selectedIds.has(i.id) && Boolean(i.holder_name))
        .map((i) => i.id),
    [items, selectedIds],
  );

  function toggleSelect(id: string) {
    setAllMatching(false);
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    setAllMatching(false);
    if (selectedIds.size === items.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(items.map((i) => i.id)));
    }
  }

  function clearSelection() {
    setAllMatching(false);
    setSelectedIds(new Set());
  }

  function selectAllMatching() {
    setSelectedIds(new Set(items.map((i) => i.id)));
    setAllMatching(true);
  }

  // A page turn starts a new page with an empty selection:
  // selectedIds spans the whole list while the checkboxes show one server
  // page, so keeping ids across a turn made "select all" compare a
  // cross-page count with the current page's length — a checkbox that lies.
  // setSelectedIds directly: clearSelection is a new function every render
  // and in the dependency array would turn this effect into a loop.
  useEffect(() => {
    setSelectedIds(new Set());
    setAllMatching(false);
  }, [skip, archivedSkip, listTab, archivedSearch]);

  const handleExport = useCallback(async () => {
    try {
      toast.loading(t("common:actions.exporting"), { id: "eq-export" });
      const blob = await itemsApi.exportXlsx({
        context_tag: "equipment",
        location_usage: "any",
      });
      downloadBlob(blob, `equipment_${getTodayFilename()}.xlsx`);
      toast.success(
        t("common:actions.exportSuccess", {
          defaultValue: "Export completed!",
        }),
        { id: "eq-export" },
      );
    } catch (error) {
      toast.error(
        extractApiError(
          error,
          t("common:actions.exportError", { defaultValue: "Export error" }),
        ),
        { id: "eq-export" },
      );
    }
  }, [t]);

  // The five handlers below are confirm-dialog `onConfirm`s, and each returns
  // its promise: the dialog waits for the answer instead of closing on the
  // click. It stays open on a refused request, and on the answers that come
  // back `200` having changed nothing — a `ReadableError` carries the reason
  // there, since the request itself did not fail. Rows that did change are
  // reported as before and the dialog closes over them.
  // Over the whole set the server sorts the deployed ones out row by row;
  // over a page the client already knows which rows it can spare the trip.
  const retireSelected = async () => {
    if (allMatching) {
      return retireMatchingMutation.mutateAsync(scope);
    }
    const deployableIds = items
      .filter((i) => getEquipmentMeta(i).status !== "DEPLOYED")
      .filter((i) => selectedIds.has(i.id))
      .map((i) => i.id);
    if (deployableIds.length === 0) {
      throw new ReadableError(t("detail.cannot_retire_deployed"));
    }
    return bulkRetireMutation.mutateAsync(deployableIds);
  };

  const handleBulkRetire = async () => {
    const result = await retireSelected();
    if (result.retired === 0 && result.errors.length > 0) {
      throw new ReadableError(failureDetail(result.errors));
    }
    if (result.errors.length > 0) {
      toast.warning(bulkOutcomeText(result.retired, result.errors.length), {
        description: failureDetail(result.errors),
      });
    } else {
      toast.success(t("list.bulk_retired", { count: result.retired }));
    }
    clearSelection();
    setShowBulkRetireConfirm(false);
  };

  // archiving is the soft delete; retiring only sets the status.
  const handleBulkArchive = async () => {
    const result = allMatching
      ? await archiveMatchingMutation.mutateAsync(scope)
      : await bulkArchiveMutation.mutateAsync([...selectedIds]);
    if (result.archived === 0 && result.errors.length > 0) {
      throw new ReadableError(failureDetail(result.errors));
    }
    if (result.errors.length > 0) {
      toast.warning(bulkOutcomeText(result.archived, result.errors.length), {
        description: failureDetail(result.errors),
      });
    } else {
      toast.success(t("list.bulk_archived", { count: result.archived }));
    }
    clearSelection();
    setShowBulkArchiveConfirm(false);
  };

  // Equipment was the one list in this workspace mode nothing could be
  // printed from, while a single asset's label sits on its detail screen.
  const handleBulkPrintLabels = useCallback(async () => {
    const codes = items
      .filter((i) => selectedIds.has(i.id))
      .map((i) => i.label_code)
      .filter((code): code is string => Boolean(code));

    if (codes.length === 0) {
      toast.error(t("list.print_no_labels"));
      return;
    }

    try {
      const blob = await labelsApi.exportPng({
        shortCodes: codes,
        width: 50,
        height: 24,
      });
      downloadBlob(blob, `equipment_labels_${codes.length}.png`);
    } catch (error) {
      toast.error(
        extractApiError(
          error,
          t("qr.downloadFailed", "Failed to download QR labels"),
        ),
      );
    }
  }, [items, selectedIds, t]);

  const openBulkReturn = useCallback(() => {
    if (returnableIds.length === 0) {
      toast.error(t("bulk_return.none_out"));
      return;
    }
    setShowBulkReturn(true);
  }, [returnableIds, t]);

  // One checkin condition for the whole batch, and only the assets that are
  // actually out — the rest would come back as "no active assignment".
  const handleBulkReturn = (choice: BulkReturnChoice) => {
    bulkReturnMutation.mutate(bulkReturnPayload(returnableIds, choice), {
      onSuccess: (result) => {
        if (result.errors.length > 0) {
          toast.warning(
            bulkOutcomeText(result.checked_in, result.errors.length),
            { description: failureDetail(result.errors) },
          );
        } else {
          toast.success(
            bulkReturnedText(t, result.checked_in, choice.condition),
          );
        }
        clearSelection();
        setShowBulkReturn(false);
      },
    });
  };

  // The backend message is English prose meant for logs. When it carries a
  // blocker code, say it in the user's language and name what holds the asset.
  const purgeRejectionText = (rejected: BulkPurgeError): string => {
    // Named `blocked`, not `count`: i18next reads `count` as a plural selector
    // and would demand _one/_few/_many variants for a number that only ever
    // appears in brackets.
    const blocked = (rejected.blocks ?? []).reduce(
      (sum, block) => sum + Number(block.count ?? 0),
      0,
    );
    if (rejected.code === "PURGE_BLOCKED_DOCUMENTS") {
      return t("list.purge_blocked_documents", { blocked });
    }
    if (rejected.code === "PURGE_BLOCKED_STOCK_TAKES") {
      return t("list.purge_blocked_stock_takes", { blocked });
    }
    return rejected.error;
  };

  const handleBulkPurge = async () => {
    const result = await bulkPurgeMutation.mutateAsync([...selectedIds]);
    if (result.purged === 0 && result.errors.length > 0) {
      throw new ReadableError(purgeRejectionText(result.errors[0]));
    }
    if (result.errors.length > 0) {
      toast.warning(bulkOutcomeText(result.purged, result.errors.length), {
        description: failureDetail(result.errors),
      });
    } else {
      toast.success(t("list.bulk_purged", { count: result.purged }));
    }
    clearSelection();
    setShowBulkPurgeConfirm(false);
  };

  const handleRestore = async (itemId: string) => {
    await restoreMutation.mutateAsync(itemId);
    toast.success(t("detail.restored"));
    setRestoreTarget(null);
  };

  const handleSinglePurge = async (itemId: string) => {
    const result = await bulkPurgeMutation.mutateAsync([itemId]);
    if (result.purged === 0) {
      throw new ReadableError(
        result.errors[0]
          ? purgeRejectionText(result.errors[0])
          : t("list.purge_failed"),
      );
    }
    toast.success(t("detail.purged"));
    setPurgeTarget(null);
  };

  const handleBulkEdit = (
    editAction: string,
    editData: Record<string, unknown>,
  ) => {
    bulkEditMutation.mutate(
      {
        item_ids: [...selectedIds],
        action: editAction as "change_status" | "change_location" | "assign_to",
        data: editData,
      },
      {
        onSuccess: (result) => {
          if (result.errors.length > 0) {
            toast.warning(
              bulkOutcomeText(result.updated, result.errors.length),
              { description: failureDetail(result.errors) },
            );
          } else {
            toast.success(t("list.bulk_edited", { count: result.updated }));
          }
          clearSelection();
          setBulkEditAction(null);
        },
      },
    );
  };

  return {
    search,
    setSearch,
    listTab,
    setListTab: (v: string) => {
      const tab = v as ListTab;
      writeListTab(tab);
      if (tab === "archived") {
        clearSelection();
      }
    },
    selectedIds,
    // How many records the next action will touch — the page's ticks, or
    // everything the filters match.
    selectedCount: allMatching ? (data?.total ?? 0) : selectedIds.size,
    allMatching,
    selectAllMatching,
    toggleSelect,
    toggleSelectAll,
    clearSelection,
    showBulkRetireConfirm,
    setShowBulkRetireConfirm,
    showBulkArchiveConfirm,
    setShowBulkArchiveConfirm,
    showBulkReturn,
    setShowBulkReturn,
    openBulkReturn,
    handleBulkPrintLabels,
    returnableCount: returnableIds.length,
    showBulkPurgeConfirm,
    setShowBulkPurgeConfirm,
    restoreTarget,
    setRestoreTarget,
    purgeTarget,
    setPurgeTarget,
    bulkEditAction,
    setBulkEditAction,
    statusFilter,
    handleStatusFilter,
    checkedOut,
    handleCheckedOutChange,
    locationFilter,
    handleLocationFilter,
    categoryFilter,
    setCategoryFilter,
    clearFiltersAndSearch,
    clearLocationAndCategory,
    sort,
    sortDir,
    handleSortChange,
    applySort,
    isLoading,
    isError,
    refetch,
    archivedLoading,
    archivedError,
    refetchArchived,
    items,
    equipmentArchived,
    hasSelection: selectedIds.size > 0,
    skip,
    limit: PAGE_SIZE,
    total: data?.total ?? 0,
    hasMore: data?.has_more ?? false,
    onPrev,
    onNext,
    resetPagination,
    // The archive's page bar, ready to spread: the archive pages by cursor.
    archivedPagination: {
      skip: archivedSkip,
      limit: PAGE_SIZE,
      total: archivedTotal,
      keyset: { rows: equipmentArchived.length, hasNext: archivedHasNext },
      onPrev: onArchivedPrev,
      onNext: onArchivedNext,
    },
    bulkRetireMutation,
    bulkArchiveMutation,
    bulkReturnMutation,
    bulkPurgeMutation,
    restoreMutation,
    bulkEditMutation,
    handleExport,
    handleBulkRetire,
    handleBulkArchive,
    handleBulkReturn,
    handleBulkPurge,
    handleRestore,
    handleSinglePurge,
    handleBulkEdit,
  };
}
