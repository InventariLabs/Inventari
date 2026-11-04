import { useState, useCallback, useEffect, useMemo } from "react";
import { pageTotal } from "@/modules/inventory/utils/pageTotal";
import type { ItemAggregates, ItemListResponse } from "@/types";
import type { TranslateFn } from "@/types/i18n";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { categoryLabel } from "@/lib/i18nHelpers";

import {
  useHiddenItemCount,
  useItemAggregates,
  useItems,
} from "@/modules/inventory/hooks/useItems";
import type {
  ItemAggregatesParams,
  ItemsParams,
} from "@/modules/inventory/hooks/useItems";
import { useModuleListFilters } from "@/modules/inventory/hooks/useModuleListFilters";
import { useLocationsById } from "@/module-sdk";
import { useOpenProductParam } from "@/modules/inventory/hooks/useOpenProductParam";
import { useScopedCategories } from "@/modules/shared/hooks/useCategories";
import { useItemsPageActions } from "@/modules/inventory/hooks/useItemsPageActions";
import { ItemsPageDialogs } from "@/modules/inventory/components/ItemsPageDialogs";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useItemFilters } from "@/modules/inventory/hooks/useItemFilters";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { ListControlBar } from "@/components/ui/ListControlBar";
import { useArchiveTabs } from "@/hooks/useArchiveTabs";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { SearchableCombobox } from "@/components/ui/SearchableCombobox";
import { LocationCombobox } from "@/module-sdk";
import { Slot } from "@/components/Slot";
import { useModules } from "@/contexts/ModulesContext";
import type { Item } from "@/types";
import ItemsBulkActionBar from "@/modules/inventory/components/items/ItemsBulkActionBar";
import { useShowModuleData } from "@/modules/settings/hooks/useOrganization";
import { useTracksExpiry } from "@/modules/shared/hooks/useTracksExpiry";
import ItemsContent from "./ItemsPage/ItemsContent";
import ItemsModalsContainer from "./ItemsPage/ItemsModalsContainer";
import { ItemsHeaderActions } from "./ItemsPage/ItemsHeaderActions";
import { ItemsMobileActionsSheet } from "./ItemsPage/ItemsMobileActionsSheet";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";

/**
 * One builder for both item queries, so the footer sums can never drift from
 * the rows above them: the aggregate query is the list query minus
 * paging and sort. Lives outside the component because every `||` here would
 * count against ItemsPage's complexity budget.
 */
function buildItemQueryParams(
  filters: ReturnType<typeof useItemFilters>,
  excludeModuleContexts: boolean,
  templateIds: string[] | undefined,
): { listParams: ItemsParams; aggregateParams: ItemAggregatesParams } {
  const aggregateParams: ItemAggregatesParams = {
    search: filters.search || undefined,
    location_id: filters.storageFilter || undefined,
    category_id: filters.categoryFilter || undefined,
    exclude_module_contexts: excludeModuleContexts,
    only_expired: filters.expiredFilter,
    expiring_days: filters.expiringFilter ? 7 : undefined,
    only_low_stock: filters.lowStockFilter || undefined,
    needs_attention: filters.attentionFilter || undefined,
    // The "show used up" chip: records with nothing left sit outside the
    // internal-usage default, so they only join the rows when asked for.
    include_empty: filters.usedUpFilter || undefined,
    // A module chip narrows to the templates it answered with; while its
    // answer is loading this is undefined, so the list stays as it was.
    template_ids: templateIds?.join(",") || undefined,
  };
  return {
    listParams: {
      ...aggregateParams,
      offset: filters.skip,
      limit: filters.limit,
      sort_by: filters.sortBy,
      sort_order: filters.sortOrder,
    },
    aggregateParams,
  };
}

/**
 * The list's count (where it stopped, if it stopped — `total_capped`) and
 * the exact count for the places that name one: the list's own when it
 * counted to the end, else the footer's — undefined until the footer
 * arrives rather than the number the list stopped at.
 */
function itemTotals(
  page: ItemListResponse | undefined,
  aggregates: ItemAggregates | undefined,
): { total: number; exactTotal: number | undefined } {
  const { total, totalCapped } = pageTotal(page);
  return { total, exactTotal: totalCapped ? aggregates?.count : total };
}

/** "records", and how many products they are of once that differs. */
function recordsLabel(
  t: TranslateFn,
  records: number,
  aggregates: ItemAggregates | undefined,
) {
  const label = t("items:recordsCount", { count: records });
  const products = aggregates?.product_count;
  return products != null && products !== records
    ? `${label} ${t("items:ofProductsCount", { count: products })}`
    : label;
}

/**
 * The list behind the "needs attention" number the dashboard and the
 * statistics card show. A chip of its own, so a reader who followed the
 * number sees the list is narrowed and can widen it.
 */
function attentionChip(
  filters: ReturnType<typeof useItemFilters>,
  label: string,
) {
  return {
    key: "needs_attention",
    label,
    active: filters.attentionFilter,
    onToggle: () => filters.setAttentionFilter(!filters.attentionFilter),
  };
}

/** The two date chips, offered where the workspace keeps dates. */
function expiryChips(
  filters: ReturnType<typeof useItemFilters>,
  expiringLabel: string,
  expiredLabel: string,
) {
  return [
    {
      key: "expiring",
      label: expiringLabel,
      active: filters.expiringFilter,
      onToggle: () => filters.setExpiringFilter(!filters.expiringFilter),
    },
    {
      key: "expired",
      label: expiredLabel,
      active: filters.expiredFilter,
      onToggle: () => filters.setExpiredFilter(!filters.expiredFilter),
    },
  ];
}

export default function ItemsPage() {
  const { t } = useTranslation(["items", "categories", "common", "labels"]);
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("items");
  const { enabledModules } = useModules();
  const navigate = useNavigate();
  const [activeModuleFilters, setActiveModuleFilters] = useState<string[]>([]);
  const moduleFilters = useModuleListFilters(
    "items",
    enabledModules,
    activeModuleFilters,
    (key) =>
      setActiveModuleFilters((prev) =>
        prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
      ),
  );
  const [searchParams] = useSearchParams();

  const [editingItemId, setEditingItemId] = useOpenProductParam();

  // A product's name opens the product dialog, the pencil's own — on the
  // desktop table and on a phone card alike. It used to open a quick-action
  // sheet first, a step no visitor expects from a name.
  const openProduct = useCallback(
    (item: Item) => setEditingItemId(item.id),
    [setEditingItemId],
  );

  const [selectedItemIds, setSelectedItemIds] = useState<string[]>([]);
  // Selection mode is a property of the list, so its trigger lives in the
  // header sheet — not on a single card. Below 1024px there is no
  // other way to reach the bulk bar.
  const [selectionMode, setSelectionMode] = useState(false);
  const [showBulkEdit, setShowBulkEdit] = useState(false);
  // `?import=1` opens the wizard straight away: the data card in settings used
  // to answer "coming soon" while this very wizard sat two clicks away, and it
  // now links here. Only for a role the wizard would actually serve — the
  // card hides itself behind `items:write`, so a deep link must not reopen
  // the door the card just closed.
  const [showImportModal, setShowImportModal] = useState(
    () => canWrite && searchParams.get("import") === "1",
  );
  const [showMobileActions, setShowMobileActions] = useState(false);
  // The retired stats inventory report grouped by category; the list
  // took that over as a toggle, off by default.
  const [groupByCategory, setGroupByCategory] = useState(false);
  const [thresholdItem, setThresholdItem] = useState<Item | null>(null);
  const [consumeDialogItem, setConsumeDialogItem] = useState<Item | null>(null);
  const [deleteReasonItem, setDeleteReasonItem] = useState<Item | null>(null);

  const filters = useItemFilters();
  const isLargeScreen = useMediaQuery("(min-width: 1024px)");
  // The one expiry decision, the same one the statistics screens read.
  const tracksExpiry = useTracksExpiry();

  // The organization decides whether the general lists carry module-owned
  // data (Settings → General). That answer scopes what this page *offers* —
  // the rows the query asks for. It does not scope naming: the places of the
  // rows on screen are read by id, including one the products query kept
  // because its category is unclaimed while its location belongs to a module.
  const excludeModuleContexts = !useShowModuleData();

  const { all: allCategories, scoped: categories } = useScopedCategories(
    filters.categoryFilter || null,
  );

  const categoryOptions = useMemo(
    () => [
      { id: "", name: t("allCategories") },
      ...(categories ?? []).map((c) => ({
        id: c.id,
        name: categoryLabel(t, c.code, c.name),
        icon: c.icon ?? undefined,
      })),
    ],
    [categories, t],
  );

  const { listParams, aggregateParams } = buildItemQueryParams(
    filters,
    excludeModuleContexts,
    moduleFilters.templateIds,
  );
  // A module chip that answered with an empty set matches nothing, and the
  // server reads an empty `template_ids` as "no filter" — so the page gives
  // that answer itself instead of asking, and shows none of the rows or sums
  // the previous filter left behind as placeholders.
  const matchesNothing = moduleFilters.templateIds?.length === 0;
  const listQuery = useItems(listParams, true, { enabled: !matchesNothing });
  const { isLoading, isError, refetch } = listQuery;
  const itemsResponse = matchesNothing ? undefined : listQuery.data;
  const isPlaceholderData = listQuery.isPlaceholderData && !matchesNothing;
  const aggregatesQuery = useItemAggregates(aggregateParams, {
    enabled: !matchesNothing,
  });
  // The chips are narrowing as much as the filters are: with one on, an
  // empty list is a filter's answer, and the controls stay to undo it.
  const isNarrowed = filters.isNarrowed || activeModuleFilters.length > 0;

  const items = useMemo(
    () => itemsResponse?.items ?? [],
    [itemsResponse?.items],
  );
  // Where the rows on screen stand, read by id: the page needs the places it
  // shows (and the one the filter names), not the organization's catalogue.
  const { byId: placesById, isLoading: placesLoading } = useLocationsById([
    ...items.map((item) => item.location_id),
    filters.storageFilter,
  ]);
  const allStorages = useMemo(() => [...placesById.values()], [placesById]);
  // Footer sums over the whole filtered set — the same params as the list
  // above minus the paging, so the two can never disagree.
  const aggregates = matchesNothing ? undefined : aggregatesQuery.data;
  const { total, exactTotal } = itemTotals(itemsResponse, aggregates);
  const hiddenCount = useHiddenItemCount(
    excludeModuleContexts,
    isLoading,
    exactTotal,
    isNarrowed,
  );
  // Narrowing tools over an empty account are eight ways to sort nothing and
  // three ways to filter it. They come back the moment there is a row — or the
  // moment the reader narrows the list themselves and needs to widen it again.
  const showControls = isLoading || total > 0 || isNarrowed;
  // The archive is a state of this list, not a place of its own — so the pair
  // of tabs stays even when the narrowing tools go, or an account whose only
  // products are archived would have no way back to them.
  const archiveTabs = useArchiveTabs("active", (tab) => {
    if (tab === "archived") navigate("/inventory/items/archived");
  });

  const handleToggleSelect = useCallback((id: string) => {
    setSelectedItemIds((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id],
    );
  }, []);

  const exitSelectionMode = useCallback(() => {
    setSelectionMode(false);
    setSelectedItemIds([]);
  }, []);

  const handleSelectAll = useCallback((ids: string[]) => {
    setSelectedItemIds(ids);
  }, []);

  const handleSetThreshold = useCallback((item: Item) => {
    setThresholdItem(item);
  }, []);

  const handlePrevPage = useCallback(() => {
    filters.setSkip(Math.max(0, filters.skip - filters.limit));
  }, [filters]);

  const handleNextPage = useCallback(() => {
    filters.setSkip(filters.skip + filters.limit);
  }, [filters]);

  const handlePageChange = useCallback(
    (page: number) => {
      filters.setSkip((page - 1) * filters.limit);
    },
    [filters],
  );

  const handleLimitChange = useCallback(
    (limit: number) => filters.setLimit(limit),
    [filters],
  );

  const {
    dialogState,
    closeDialog,
    deleteMutation,
    consumeMutation,
    handleConsume,
    handleAddOne,
    handleDelete,
    handleSwipeDelete,
    handleBulkDelete,
    handleExport,
  } = useItemsPageActions({
    items,
    storageFilter: filters.storageFilter,
    exportParams: aggregateParams,
    storages: allStorages,
    setConsumeDialogItem,
    setDeleteReasonItem,
  });

  useEffect(() => {
    setHeader({
      actions: (
        <ItemsHeaderActions
          selectionMode={selectionMode}
          canWrite={canWrite}
          hasRows={total > 0}
          onExitSelectionMode={exitSelectionMode}
          onOpenMobileActions={() => setShowMobileActions(true)}
          onImport={() => setShowImportModal(true)}
          onExport={handleExport}
          onAddProduct={() => navigate("/inventory/items/add")}
        />
      ),
    });
  }, [
    setHeader,
    handleExport,
    navigate,
    selectionMode,
    exitSelectionMode,
    total,
    canWrite,
  ]);

  const itemsFilters = useMemo(
    () => ({
      skip: filters.skip,
      limit: filters.limit,
      sortBy: filters.sortBy,
      sortOrder: filters.sortOrder,
    }),
    [filters.skip, filters.limit, filters.sortBy, filters.sortOrder],
  );

  // The module chips are the page's own state, so the way back widens them
  // beside the hook's own controls — one click for every narrowing tool.
  const clearFilters = () => {
    filters.clearFilters();
    setActiveModuleFilters([]);
  };

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="items" />
      <Slot name="items_page_header_extra" />

      <ItemsPageDialogs
        dialogState={dialogState}
        closeDialog={closeDialog}
        deleteReasonItem={deleteReasonItem}
        onDelete={async (item, reason, notes) => {
          // Awaited, so a refused delete leaves the dialog standing with the
          // reason and note as typed instead of closing over nothing.
          await deleteMutation.mutateAsync(item.id, reason, notes);
          setDeleteReasonItem(null);
        }}
        onDeleteCancel={() => setDeleteReasonItem(null)}
        consumeDialogItem={consumeDialogItem}
        onConsume={async (item, quantity, reason, notes) => {
          await consumeMutation.mutateAsync(item.id, quantity, reason, notes);
          setConsumeDialogItem(null);
        }}
        onConsumeCancel={() => setConsumeDialogItem(null)}
      />

      {showControls ? (
        <ListControlBar
          primaryTabs={archiveTabs}
          search={{
            value: filters.searchInput,
            onChange: filters.setSearchInput,
            placeholder: t("searchPlaceholder"),
          }}
          filterButton={{
            activeCount:
              (filters.storageFilter ? 1 : 0) +
              (filters.categoryFilter ? 1 : 0) +
              (filters.usedUpFilter ? 1 : 0),
            onClick: () => filters.setShowFilters(!filters.showFilters),
          }}
          secondaryFilters={[
            attentionChip(filters, t("needsAttention")),
            // The same decision the statistics screens read. Offered
            // unconditionally, these two chips contradicted a health card that
            // had just said this workspace keeps no dates.
            ...(tracksExpiry
              ? expiryChips(filters, t("onlyExpiring"), t("stats.expired"))
              : []),
            {
              key: "low_stock",
              label: t("onlyLowStock"),
              active: filters.lowStockFilter,
              onToggle: () =>
                filters.setLowStockFilter(!filters.lowStockFilter),
            },
            {
              key: "used_up",
              label: t("showUsedUp"),
              active: filters.usedUpFilter,
              onToggle: () => filters.setUsedUpFilter(!filters.usedUpFilter),
            },
            {
              key: "group_by_category",
              label: t("groupByCategory"),
              active: groupByCategory,
              onToggle: () => setGroupByCategory((prev) => !prev),
            },
            ...moduleFilters.chips,
          ]}
          resultCount={isError ? undefined : exactTotal}
          // One row per record of stock, not per product: the count says so,
          // and names the products too, the unit a shortage is counted in and
          // a category card says: "6 records · 3 products".
          resultCountLabel={recordsLabel(t, exactTotal ?? 0, aggregates)}
          primaryAction={
            /* Eight options do not need a search box, but they do not need the
             full width of a 1920px screen either. The bar's own slot keeps
             the sort control off its own band. */
            <NativeSelect
              wrapperClassName="w-fit max-w-xs"
              aria-label={t("sort.label")}
              className="text-xs"
              value={`${filters.sortBy}_${filters.sortOrder}`}
              onChange={(e) => {
                const parts = e.target.value.split("_");
                const order = parts.pop() as "asc" | "desc";
                const by = parts.join("_") as typeof filters.sortBy;
                filters.setSort(by, order);
              }}
            >
              <option value="created_at_desc">{t("sort.newest")}</option>
              <option value="created_at_asc">{t("sort.oldest")}</option>
              <option value="name_asc">{t("sort.nameAsc")}</option>
              <option value="name_desc">{t("sort.nameDesc")}</option>
              <option value="quantity_asc">{t("sort.quantityAsc")}</option>
              <option value="quantity_desc">{t("sort.quantityDesc")}</option>
              <option value="expiry_date_asc">{t("sort.expiryAsc")}</option>
              <option value="expiry_date_desc">{t("sort.expiryDesc")}</option>
            </NativeSelect>
          }
        />
      ) : (
        <ListControlBar
          primaryTabs={archiveTabs}
          // An empty default view is exactly the state a consumed record
          // leaves behind, and the narrowing tools are gone with it — keep
          // the one chip that asks whether something is hiding, so the way
          // back does not depend on other rows existing.
          secondaryFilters={[
            {
              key: "used_up",
              label: t("showUsedUp"),
              active: filters.usedUpFilter,
              onToggle: () => filters.setUsedUpFilter(!filters.usedUpFilter),
            },
          ]}
        />
      )}

      {filters.showFilters && (
        <div
          id="items-domain-filters"
          className="grid grid-cols-1 gap-2 sm:grid-cols-2 items-end sm:gap-3 lg:grid-cols-3 xl:grid-cols-4 p-3 sm:p-4 bg-surface-card rounded-xl border border-border animate-in slide-in-from-top-2 duration-200"
        >
          <LocationCombobox
            label={t("table.location")}
            title={t("table.location")}
            value={filters.storageFilter}
            onChange={filters.setStorageFilter}
            placeholder={t("allPlaces")}
            searchPlaceholder={t("common:actions.search")}
            emptyMessage={t("common:noResults")}
            clearable
            clearLabel={t("allPlaces")}
          />
          <SearchableCombobox
            label={t("table.category")}
            title={t("table.category")}
            options={categoryOptions}
            value={filters.categoryFilter}
            onChange={filters.setCategoryFilter}
            placeholder={t("allCategories")}
            searchPlaceholder={t("common:actions.search")}
            emptyMessage={t("common:noResults")}
          />
        </div>
      )}

      <ItemsContent
        canWrite={canWrite}
        isError={isError}
        isLoading={isLoading}
        itemsResponse={itemsResponse}
        items={items}
        total={total}
        aggregates={aggregates}
        groupByCategory={groupByCategory}
        hiddenCount={hiddenCount}
        hasFilters={isNarrowed}
        onClearFilters={clearFilters}
        isPlaceholderData={isPlaceholderData}
        isLargeScreen={isLargeScreen}
        // No place is printed while the places that name the rows are on their
        // way; "Unknown" is for a place the arrived answer does not hold.
        storages={placesLoading ? undefined : allStorages}
        categories={allCategories}
        filters={{
          ...itemsFilters,
          searchInput: filters.searchInput,
          setSearchInput: filters.setSearchInput,
        }}
        enabledModules={enabledModules}
        selectedItemIds={selectedItemIds}
        selectionMode={selectionMode}
        consumingId={
          consumeMutation.isPending
            ? (consumeMutation.variables?.itemId ?? null)
            : null
        }
        onItemClick={openProduct}
        onConsume={handleConsume}
        onAddOne={handleAddOne}
        onEdit={setEditingItemId}
        onDelete={handleDelete}
        onSwipeDelete={handleSwipeDelete}
        onToggleSelect={handleToggleSelect}
        onSelectAll={handleSelectAll}
        onSetThreshold={handleSetThreshold}
        onRefetch={refetch}
        onPrevPage={handlePrevPage}
        onNextPage={handleNextPage}
        onPageChange={handlePageChange}
        onLimitChange={handleLimitChange}
      />

      <ItemsBulkActionBar
        canWrite={canWrite}
        selectedIds={selectedItemIds}
        totalInResult={exactTotal ?? 0}
        enabledModules={enabledModules}
        isPendingDelete={deleteMutation.isPending}
        onClearSelection={() => setSelectedItemIds([])}
        onBulkEdit={() => setShowBulkEdit(true)}
        onBulkDelete={() =>
          handleBulkDelete(selectedItemIds, () => setSelectedItemIds([]))
        }
      />

      <ItemsModalsContainer
        editingItemId={editingItemId}
        setEditingItemId={setEditingItemId}
        thresholdItem={thresholdItem}
        setThresholdItem={setThresholdItem}
        showBulkEdit={showBulkEdit}
        setShowBulkEdit={setShowBulkEdit}
        selectedItemIds={selectedItemIds}
        setSelectedItemIds={setSelectedItemIds}
        showImportModal={showImportModal}
        setShowImportModal={setShowImportModal}
      />

      <ItemsMobileActionsSheet
        open={showMobileActions}
        canWrite={canWrite}
        hasRows={total > 0}
        onClose={() => setShowMobileActions(false)}
        onImport={() => setShowImportModal(true)}
        onExport={handleExport}
        onOpenCategories={() => navigate("/inventory/categories")}
        onSelectItems={() => setSelectionMode(true)}
      />
    </div>
  );
}
