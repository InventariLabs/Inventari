import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Monitor, X, MapPin } from "lucide-react";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { Button } from "@/components/ui/Button";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { NativeSelect } from "@/components/ui/NativeSelect";
import ImportEquipmentModal from "@/modules/equipment/components/ImportEquipmentModal";
import { BulkReturnModal } from "@/modules/equipment/components/BulkReturnModal";
import { ListControlBar } from "@/components/ui/ListControlBar";
import { GettingStarted } from "@/components/ui/GettingStarted";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryError } from "@/components/ui/QueryResult";
import { Pagination } from "@/module-sdk";
import { AssetBulkActionsBar } from "@/modules/equipment/components/AssetBulkActionsBar";
import { selectedLabelTarget } from "@/modules/equipment/lib/printTarget";
import { AssetListHeaderActions } from "@/modules/equipment/components/AssetListHeaderActions";
import { AssetCardRow } from "@/modules/equipment/components/AssetCardRow";
import {
  CategoryFilter,
  LocationFilter,
} from "@/modules/equipment/components/AssetFilterSelects";
import { ClearableFilterBadge } from "@/modules/equipment/components/ClearableFilterBadge";
import { useAssetImage } from "@/modules/equipment/hooks/useAssetImage";
import { useLocationLabel } from "@/modules/equipment/hooks/useLocationLabel";
import { AssetTable } from "@/modules/equipment/components/AssetTable";
import { ArchivedAssetRow } from "@/modules/equipment/components/ArchivedAssetRow";
import { ArchivedEmptyState } from "@/modules/equipment/components/ArchivedEmptyState";
import { AssetConfirmDialogs } from "@/modules/equipment/components/AssetConfirmDialogs";
import { BulkEditDialogs } from "@/modules/equipment/components/BulkEditDialogs";
import { useAllCategories } from "@/modules/shared/hooks/useCategories";
import { useLocationsById } from "@/module-sdk";
import { ASSET_STATUSES } from "@/modules/equipment/hooks/useAssetListActions";
import { useAssetListActions } from "@/modules/equipment/hooks/useAssetListActions";

/**
 * What an empty list says: the narrowing that emptied it, most specific
 * first. A phrase alone is "nothing matches" — the first-run state belongs to
 * an empty register, which has its own screen.
 */
function emptyHeading(
  t: TFunction,
  f: {
    statusFilter: string;
    statusLabel: string;
    checkedOut: boolean;
    hasListFilters: boolean;
  },
) {
  if (f.statusFilter) {
    return t("equipment:list.empty_filtered_status", { status: f.statusLabel });
  }
  if (f.checkedOut) return t("equipment:list.empty_filtered_checked_out");
  if (f.hasListFilters) return t("equipment:list.empty_filtered");
  return t("equipment:list.no_results");
}

/**
 * Whether a chip of the status segment is lit. "Checked Out" is also what the
 * address's checked_out flag asks for, so it lights for that flag, and "All"
 * only when neither narrows the list.
 */
function segmentLit(key: string, statusFilter: string, checkedOut: boolean) {
  if (key === "all") return !statusFilter && !checkedOut;
  return statusFilter === key || (key === "DEPLOYED" && checkedOut);
}

export default function AssetListPage() {
  const { t } = useTranslation("equipment");
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("equipment");
  const [showImport, setShowImport] = useState(false);

  const {
    search,
    setSearch,
    listTab,
    setListTab,
    selectedIds,
    selectedCount,
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
    returnableCount,
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
    hideRetired,
    handleHideRetiredChange,
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
    hasSelection,
    skip,
    limit,
    total,
    onPrev,
    onNext,
    resetPagination,
    archivedPagination,
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
  } = useAssetListActions();

  const {
    data: allCategories = [],
    error: categoriesError,
    refetch: refetchCategories,
  } = useAllCategories();
  // Both filters on this screen answer the same question — what equipment may
  // call its own. A category enters by its tag or by having none; a location
  // enters by its tag or by holding this module's records, which is the union
  // `moduleScope` resolves (the scope the module's own locations screen
  // lists). The location pickers search that scope on the server; the one
  // place the screen names itself is the location it is narrowed to.
  const { byId: narrowedTo } = useLocationsById([locationFilter]);
  const assetImage = useAssetImage();
  const locationLabel = useLocationLabel(items.map((i) => i.location_id));

  const [showFilters, setShowFilters] = useState(
    !!(locationFilter || categoryFilter),
  );

  const hasListFilters = Boolean(
    statusFilter ||
    checkedOut ||
    hideRetired ||
    locationFilter ||
    categoryFilter,
  );
  const statusLabel = statusFilter
    ? t(`status.${statusFilter.toLowerCase()}` as const)
    : "";

  /**
   * On a filtered list that runs past one page, "Select All" was a promise the
   * button could not keep.
   *
   * The select branch keeps the page/all distinction — it is real there: only
   * this page's ticks move. The deselect branch clears the whole selection,
   * exactly what the bulk bar's X button does, so it borrows that button's
   * words: one action, one name (UI_GUIDELINES §14.4). "Deselect page" beside
   * a "Clear selection" X was the same click wearing two labels.
   *
   * Each branch calls `t` with a literal key: the i18n gate reads the call
   * sites, and a ternary *inside* `t()` hides every key it chooses between.
   * The arrow keeps the branching out of this component's complexity budget.
   */
  const selectionLabel = (() => {
    const pageScoped = total > items.length;
    if (selectedIds.size === items.length) {
      return t("common:actions.clearSelection");
    }
    return pageScoped ? t("actions.select_page") : t("actions.select_all");
  })();

  const handleClearFilters = () => {
    clearFiltersAndSearch();
    resetPagination();
  };

  useEffect(() => {
    setHeader({
      actions: (
        <AssetListHeaderActions
          canWrite={canWrite}
          onExport={handleExport}
          onImport={() => setShowImport(true)}
        />
      ),
    });
  }, [setHeader, handleExport, canWrite]);

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="equipment" />
      <ListControlBar
        search={{
          value: search,
          onChange: setSearch,
          placeholder: t("list.search", "Search assets…"),
        }}
        primaryTabs={{
          value: listTab,
          onChange: setListTab,
          options: [
            // the tab scopes to non-archived assets — label it
            // truthfully so it no longer duplicates the "All" status chip.
            { value: "active", label: t("list.active_tab") },
            { value: "archived", label: t("list.archived_tab") },
          ],
        }}
        secondaryFilters={
          listTab === "active"
            ? [
                {
                  key: "all",
                  label: t("list.all_statuses", "All"),
                  active: segmentLit("all", statusFilter, checkedOut),
                  onToggle: () => handleStatusFilter(""),
                },
                ...ASSET_STATUSES.map((s) => ({
                  key: s,
                  label: t(`status.${s.toLowerCase()}` as const),
                  active: segmentLit(s, statusFilter, checkedOut),
                  onToggle: () => handleStatusFilter(s),
                })),
              ]
            : undefined
        }
        filterButton={
          listTab === "active"
            ? {
                activeCount:
                  (locationFilter ? 1 : 0) + (categoryFilter ? 1 : 0),
                onClick: () => setShowFilters((v) => !v),
              }
            : undefined
        }
        primaryAction={
          /* Six options do not need the full width of a 1920px screen. Left
             in a flex row of its own below the bar, the select stretched
             across the page as an empty band, and the screen stacked four
             rows of controls before the first record. The bar's own slot is
             where the product list keeps the same control. */
          listTab === "active" ? (
            <NativeSelect
              wrapperClassName="w-fit max-w-xs"
              value={`${sort}:${sortDir}`}
              onChange={(e) => {
                const [key, dir] = e.target.value.split(":");
                applySort(key as typeof sort, dir as typeof sortDir);
              }}
              className="text-xs"
              aria-label={t("list.sort.label", "Sort assets")}
            >
              <option value="created_at:desc">{t("list.sort.newest")}</option>
              <option value="created_at:asc">{t("list.sort.oldest")}</option>
              <option value="name:asc">{t("list.sort.name")}</option>
              <option value="warranty_until:asc">
                {t("list.sort.warranty")}
              </option>
              <option value="location:asc">{t("list.sort.location")}</option>
              <option value="purchase_price:desc">
                {t("list.sort.price")}
              </option>
            </NativeSelect>
          ) : undefined
        }
      />

      {listTab === "active" && locationFilter && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-primary-50 dark:bg-primary-900/30 border border-primary-200 dark:border-primary-800 text-xs text-primary-700 dark:text-primary-200">
          {/* Named narrowing: arriving from a location card, the list says
              what it is scoped to and hands back the way out — silent
              narrowing reads as a broken list. */}
          <MapPin size={14} className="shrink-0" />
          <span>
            {t("list.narrowed_to_location", {
              name: narrowedTo.get(locationFilter)?.name ?? locationFilter,
            })}
          </span>
          <Button
            variant="ghost"
            size="iconSm"
            onClick={() => handleLocationFilter("")}
            aria-label={t("list.clear_narrowed")}
            className="text-primary-700 dark:text-primary-200"
          >
            ✕
          </Button>
        </div>
      )}

      {listTab === "active" && (
        <div className="flex items-center gap-2 flex-wrap">
          {showFilters && (
            <LocationFilter
              value={locationFilter}
              onChange={(value) => {
                handleLocationFilter(value);
                resetPagination();
              }}
            />
          )}
          {showFilters && (
            <CategoryFilter
              value={categoryFilter}
              onChange={(value) => {
                setCategoryFilter(value);
                resetPagination();
              }}
              options={allCategories}
              error={categoriesError}
              onRetry={refetchCategories}
            />
          )}
          {showFilters && (locationFilter || categoryFilter) && (
            <Button
              variant="ghost"
              size="sm"
              className="text-xs text-on-muted"
              onClick={() => {
                clearLocationAndCategory();
                resetPagination();
              }}
            >
              {t("list.clear_filters", "Clear")}
            </Button>
          )}
        </div>
      )}

      {hasSelection && canWrite && (
        <AssetBulkActionsBar
          selectedCount={selectedCount}
          unreachedMatches={allMatching ? 0 : Math.max(0, total - items.length)}
          matchingTotal={total}
          allMatching={allMatching}
          onSelectAllMatching={selectAllMatching}
          listTab={listTab}
          onBulkRetire={() => setShowBulkRetireConfirm(true)}
          onBulkArchive={() => setShowBulkArchiveConfirm(true)}
          onBulkReturn={openBulkReturn}
          onBulkPrintLabels={handleBulkPrintLabels}
          printTarget={selectedLabelTarget(items, selectedIds)}
          onBulkPurge={() => setShowBulkPurgeConfirm(true)}
          onBulkChangeStatus={() => setBulkEditAction("change_status")}
          onBulkChangeLocation={() => setBulkEditAction("change_location")}
          onBulkAssignTo={() => setBulkEditAction("assign_to")}
          onClearSelection={clearSelection}
        />
      )}

      {listTab === "active" && (
        <>
          {isError ? (
            <QueryError onRetry={() => refetch()} />
          ) : isLoading ? (
            <LoadingSpinner />
          ) : items.length === 0 &&
            !search &&
            !statusFilter &&
            !checkedOut &&
            !hideRetired &&
            !locationFilter &&
            !categoryFilter ? (
            <GettingStarted
              moduleName="equipment"
              icon={Monitor}
              description={t("list.gettingStarted.description")}
              steps={[
                {
                  title: t("list.gettingStarted.step1.title"),
                  description: t("list.gettingStarted.step1.description"),
                  ctaLabel: t("list.gettingStarted.step1.cta"),
                  ctaTo: "/equipment/add",
                },
                {
                  title: t("list.gettingStarted.stepImport.title"),
                  description: t("list.gettingStarted.stepImport.description"),
                  ctaLabel: t("list.gettingStarted.stepImport.cta"),
                  onCta: () => setShowImport(true),
                },
                {
                  title: t("list.gettingStarted.step2.title"),
                  description: t("list.gettingStarted.step2.description"),
                },
                {
                  title: t("list.gettingStarted.step3.title"),
                  description: t("list.gettingStarted.step3.description"),
                },
              ]}
            />
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <Monitor size={48} className="text-on-muted/40 mb-4" />
              <h3 className="text-lg font-semibold text-on mb-1">
                {emptyHeading(t, {
                  statusFilter,
                  statusLabel,
                  checkedOut,
                  hasListFilters,
                })}
              </h3>
              {(hasListFilters || search) && (
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-5"
                  leftIcon={<X size={14} />}
                  onClick={handleClearFilters}
                >
                  {t("list.clear_filters", "Clear")}
                </Button>
              )}
            </div>
          ) : (
            <div className="space-y-2">
              <div className="flex items-center gap-2 px-1 mb-1">
                {canWrite && (
                  <Button
                    size="content"
                    type="button"
                    variant="ghost"
                    onClick={toggleSelectAll}
                    className="h-8 px-1.5 text-xs text-on-muted hover:text-on hover:bg-transparent active:bg-transparent"
                  >
                    {selectionLabel}
                  </Button>
                )}
                <span className="text-xs text-on-muted">
                  {t("list.showing", {
                    count: total,
                    defaultValue: `${total} assets`,
                  })}
                </span>
                {statusFilter && (
                  <ClearableFilterBadge
                    label={statusLabel}
                    clearLabel={t("list.clear_filter", "Clear status filter")}
                    onClear={() => handleStatusFilter("")}
                  />
                )}
                {hideRetired && (
                  <ClearableFilterBadge
                    label={t("list.retired_hidden")}
                    clearLabel={t("list.show_retired")}
                    onClear={() => handleHideRetiredChange(false)}
                  />
                )}
                {checkedOut && (
                  <ClearableFilterBadge
                    label={t("status.deployed")}
                    clearLabel={t(
                      "list.clear_checked_out",
                      "Clear checked-out filter",
                    )}
                    onClear={() => handleCheckedOutChange(false)}
                  />
                )}
              </div>
              {/* Table on desktop, enriched cards on mobile. */}
              <div className="hidden md:block">
                <AssetTable
                  items={items}
                  selectable={canWrite}
                  selectedIds={selectedIds}
                  onToggleSelect={toggleSelect}
                  onToggleSelectAll={toggleSelectAll}
                  sort={sort}
                  sortDir={sortDir}
                  onSortChange={handleSortChange}
                  locationLabel={locationLabel}
                />
              </div>
              <div className="md:hidden space-y-2">
                {items.map((item) => (
                  <AssetCardRow
                    key={item.id}
                    item={item}
                    selectable={canWrite}
                    isSelected={selectedIds.has(item.id)}
                    onToggleSelect={toggleSelect}
                    image={assetImage(item)}
                    locationName={locationLabel(
                      item.location_id,
                      item.location_name,
                    )}
                  />
                ))}
              </div>
              <Pagination
                skip={skip}
                limit={limit}
                total={total}
                onPrev={onPrev}
                onNext={onNext}
              />
            </div>
          )}
        </>
      )}

      {listTab === "archived" && (
        <>
          {archivedError ? (
            <QueryError onRetry={() => refetchArchived()} />
          ) : archivedLoading ? (
            <LoadingSpinner />
          ) : equipmentArchived.length === 0 ? (
            <ArchivedEmptyState search={search} />
          ) : (
            <div className="divide-y divide-border">
              {equipmentArchived.map((item) => (
                <ArchivedAssetRow
                  key={item.id}
                  item={item}
                  selectable={canWrite}
                  isSelected={selectedIds.has(item.id)}
                  isRestorePending={restoreMutation.isPending}
                  isPurgePending={bulkPurgeMutation.isPending}
                  onToggleSelect={toggleSelect}
                  onRestore={(id) => setRestoreTarget(id)}
                  onPurge={(id) => setPurgeTarget(id)}
                />
              ))}
            </div>
          )}
          <Pagination {...archivedPagination} />
        </>
      )}

      {showImport && (
        <ImportEquipmentModal onClose={() => setShowImport(false)} />
      )}

      {showBulkReturn && (
        <BulkReturnModal
          selectedCount={selectedCount}
          returnableCount={returnableCount}
          isPending={bulkReturnMutation.isPending}
          onConfirm={handleBulkReturn}
          onClose={() => setShowBulkReturn(false)}
        />
      )}

      <AssetConfirmDialogs
        selectedCount={selectedCount}
        showBulkRetireConfirm={showBulkRetireConfirm}
        showBulkArchiveConfirm={showBulkArchiveConfirm}
        showBulkPurgeConfirm={showBulkPurgeConfirm}
        restoreTarget={restoreTarget}
        purgeTarget={purgeTarget}
        onBulkRetire={handleBulkRetire}
        onBulkArchive={handleBulkArchive}
        onBulkPurge={handleBulkPurge}
        onRestore={handleRestore}
        onSinglePurge={handleSinglePurge}
        onCancelBulkRetire={() => setShowBulkRetireConfirm(false)}
        onCancelBulkArchive={() => setShowBulkArchiveConfirm(false)}
        onCancelBulkPurge={() => setShowBulkPurgeConfirm(false)}
        onCancelRestore={() => setRestoreTarget(null)}
        onCancelPurge={() => setPurgeTarget(null)}
      />

      {bulkEditAction && (
        <BulkEditDialogs
          action={bulkEditAction}
          selectedCount={selectedCount}
          onConfirm={handleBulkEdit}
          onCancel={() => setBulkEditAction(null)}
          isPending={bulkEditMutation.isPending}
        />
      )}
    </div>
  );
}
