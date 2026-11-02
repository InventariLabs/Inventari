import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Card } from "@/components/ui/Card";
import { useHasPermission } from "@/hooks/useHasPermission";
import ItemTable from "@/modules/inventory/components/items/ItemTable";
import ItemMobileCard from "@/modules/inventory/components/items/ItemMobileCard";
import { useNavigate } from "react-router-dom";
import ItemActionsSheet from "@/modules/inventory/components/items/ItemActionsSheet";
import { groupItemsByCategory } from "@/modules/inventory/components/items/groupItemsByCategory";
import { MoveItemModal } from "@/modules/inventory/components/MoveItemModal";
import ItemsPagination from "@/modules/inventory/components/items/ItemsPagination";
import ItemsTotalsFooter from "@/modules/inventory/components/items/ItemsTotalsFooter";
import ItemsEmptyState from "@/modules/inventory/components/items/ItemsEmptyState";
import { HiddenRecordsNotice } from "@/modules/shared/components/HiddenRecordsNotice";
import { QueryError } from "@/components/ui/QueryResult";
import type {
  Item,
  CategoryDTO,
  ItemAggregates,
  StorageLocationSummary,
} from "@/types";

interface ItemsContentProps {
  isError: boolean;
  isLoading: boolean;
  itemsResponse:
    { items: Item[]; total: number; total_capped?: boolean } | undefined;
  items: Item[];
  total: number;
  /** Whole-set sums for the footer — undefined while the query loads. */
  aggregates?: ItemAggregates;
  /** Group rows under per-category headers. */
  groupByCategory?: boolean;
  /** Rows the module filter keeps off the list; 0 until a probe says more. */
  hiddenCount?: number;
  /** A filter or chip is on — the empty answer below belongs to it. */
  hasFilters: boolean;
  /** Widens the list back to every row the account has. */
  onClearFilters: () => void;
  isPlaceholderData: boolean;
  isLargeScreen: boolean;
  storages: StorageLocationSummary[] | undefined;
  categories: CategoryDTO[] | undefined;
  filters: {
    searchInput?: string;
    setSearchInput?: (value: string) => void;
    skip: number;
    limit: number;
    sortBy?: "created_at" | "name" | "quantity" | "expiry_date";
    sortOrder?: "asc" | "desc";
  };
  enabledModules: string[];
  selectedItemIds: string[];
  selectionMode: boolean;
  /** Whether the reader may change products; threaded to every row. */
  canWrite?: boolean;
  consumingId: string | null;
  onItemClick: (item: Item) => void;
  onConsume: (id: string) => void;
  onAddOne: (id: string) => void;
  onEdit: (id: string) => void;
  /** Asks for confirmation first — the row menu and the actions sheet. */
  onDelete: (id: string) => void;
  /** Deletes without a second question: the swipe's Undo window is the
 confirmation. */
  onSwipeDelete: (id: string) => void;
  onToggleSelect: (id: string) => void;
  onSelectAll: (ids: string[]) => void;
  onSetThreshold: (item: Item) => void;
  onRefetch: () => void;
  onPrevPage: () => void;
  onNextPage: () => void;
  onPageChange: (page: number) => void;
  onLimitChange: (limit: number) => void;
}

export default function ItemsContent({
  isError,
  isLoading,
  itemsResponse,
  items,
  total,
  aggregates,
  groupByCategory = false,
  hiddenCount,
  hasFilters,
  onClearFilters,
  isPlaceholderData,
  isLargeScreen,
  storages,
  categories,
  filters,
  enabledModules,
  selectedItemIds,
  selectionMode,
  consumingId,
  onItemClick,
  onConsume,
  onAddOne,
  onEdit,
  onDelete,
  onSwipeDelete,
  onToggleSelect,
  onSelectAll,
  onSetThreshold,
  onRefetch,
  onPrevPage,
  onNextPage,
  onPageChange,
  onLimitChange,
  canWrite = true,
}: ItemsContentProps) {
  const { t } = useTranslation(["items", "common"]);
  // Deleting a product is `items:delete`, not `items:write`: the endpoint
  // checks the narrower key, and every delete surface the list owns asks it
  // here rather than riding on `canWrite`.
  const canDelete = useHasPermission("items:delete");
  const navigate = useNavigate();
  // Which item the actions sheet is open for; null = closed. Mobile-only in
  // practice — the desktop table row exposes its actions inline.
  const [actionsItem, setActionsItem] = useState<Item | null>(null);
  const [movingItem, setMovingItem] = useState<Item | null>(null);
  const mobileGroups = useMemo(
    () =>
      groupByCategory
        ? groupItemsByCategory(items, categories, t("common:noCategory"), t)
        : null,
    [groupByCategory, items, categories, t],
  );
  if (isError) {
    return <QueryError onRetry={onRefetch} />;
  }

  if (isLoading && !itemsResponse) {
    return (
      <Card className="flex flex-col items-center justify-center py-20 border-dashed border">
        <p className="text-on-muted font-medium uppercase tracking-widest text-xs">
          {t("loadingProducts")}
        </p>
      </Card>
    );
  }

  if (items.length === 0) {
    const searchTerm = filters.searchInput?.trim() || "";
    const setSearch = filters.setSearchInput;
    const onClear = setSearch
      ? () => {
          setSearch("");
        }
      : undefined;
    return (
      <ItemsEmptyState
        canWrite={canWrite}
        hasFilters={hasFilters}
        searchTerm={searchTerm}
        onClearSearch={searchTerm ? onClear : undefined}
        onClearFilters={onClearFilters}
        hiddenCount={hiddenCount}
      />
    );
  }

  return (
    <div
      className={`transition-opacity duration-200 ${isPlaceholderData ? "opacity-50 pointer-events-none" : "opacity-100"}`}
    >
      {/* The hidden counter belongs to the list, not to its empty state: a
          row in view used to silence it, and one hidden record behind three
          visible ones is exactly the case nobody spots alone. */}
      {items.length > 0 && (hiddenCount ?? 0) > 0 && (
        <div className="mb-3">
          <HiddenRecordsNotice
            message={t("hidden.inlineCount", { count: hiddenCount })}
            actionLabel={t("hidden.openSettings")}
          />
        </div>
      )}
      {isLargeScreen ? (
        <ItemTable
          canWrite={canWrite}
          canDelete={canDelete}
          items={items}
          storages={storages}
          categories={categories}
          enabledModules={enabledModules}
          sortBy={filters.sortBy}
          sortOrder={filters.sortOrder}
          groupByCategory={groupByCategory}
          onItemClick={onItemClick}
          onConsume={onConsume}
          onAddOne={onAddOne}
          onEdit={onEdit}
          onDelete={onDelete}
          consumingId={consumingId}
          selectedIds={selectedItemIds}
          onToggleSelect={onToggleSelect}
          onSelectAll={onSelectAll}
          onSetThreshold={onSetThreshold}
        />
      ) : mobileGroups ? (
        <div className="space-y-2 pb-4">
          {/* The swipe hint belongs to the first card on the page, whichever
              group it landed in — a flat index would restart per group. */}
          {(() => {
            let cardIndex = 0;
            return mobileGroups.map((group) => (
              <div key={group.key} className="space-y-2">
                <div className="flex items-center gap-2 px-1 pt-2">
                  {group.icon && (
                    <span className="text-base">{group.icon}</span>
                  )}
                  <span className="text-[10px] font-medium uppercase tracking-widest text-on-secondary">
                    {group.label}
                  </span>
                  <span className="text-[10px] text-on-muted tabular-nums">
                    {t("totals.positions", { count: group.items.length })}
                  </span>
                </div>
                {group.items.map((item) => {
                  const isFirstCard = cardIndex === 0;
                  cardIndex += 1;
                  return (
                    <ItemMobileCard
                      key={item.id}
                      canWrite={canWrite}
                      item={item}
                      storages={storages}
                      categories={categories}
                      onItemClick={onItemClick}
                      onConsume={onConsume}
                      onSwipeDelete={canDelete ? onSwipeDelete : undefined}
                      onOpenActions={setActionsItem}
                      consumingId={consumingId}
                      isSelected={selectedItemIds.includes(item.id)}
                      onToggleSelect={onToggleSelect}
                      onSetThreshold={onSetThreshold}
                      selectionMode={selectionMode}
                      swipeHint={isFirstCard}
                    />
                  );
                })}
              </div>
            ));
          })()}
        </div>
      ) : (
        <div className="space-y-2 pb-4">
          {items.map((item, index) => (
            <ItemMobileCard
              key={item.id}
              canWrite={canWrite}
              item={item}
              storages={storages}
              categories={categories}
              onItemClick={onItemClick}
              onConsume={onConsume}
              onSwipeDelete={canDelete ? onSwipeDelete : undefined}
              onOpenActions={setActionsItem}
              consumingId={consumingId}
              isSelected={selectedItemIds.includes(item.id)}
              onToggleSelect={onToggleSelect}
              onSetThreshold={onSetThreshold}
              selectionMode={selectionMode}
              swipeHint={index === 0}
            />
          ))}
        </div>
      )}

      {/* The per-row ⋮ menu. Owned by the list (like every other modal on
          this page), so the card's transform/overflow never traps it. */}
      <ItemActionsSheet
        canWrite={canWrite}
        canDelete={canDelete}
        item={actionsItem ?? items[0]}
        open={actionsItem !== null}
        onClose={() => setActionsItem(null)}
        onConsume={onConsume}
        onAddOne={onAddOne}
        onEdit={onItemClick}
        onViewDetails={(item) => navigate(`/inventory/items/${item.id}`)}
        onMove={setMovingItem}
        onSetThreshold={onSetThreshold}
        onDelete={onDelete}
      />

      {movingItem && (
        <MoveItemModal
          item={movingItem}
          onClose={() => setMovingItem(null)}
          onSuccess={() => setMovingItem(null)}
        />
      )}

      {/* Whole-set sums sit between the list and the pager — the pager
          answers "where am I", the footer answers "how much is this". */}
      <ItemsTotalsFooter aggregates={aggregates} />

      <ItemsPagination
        skip={filters.skip}
        limit={filters.limit}
        total={total}
        // The list stopped counting at `total` — see `Pagination`.
        totalCapped={itemsResponse?.total_capped}
        onPrev={onPrevPage}
        onNext={onNextPage}
        onPageChange={onPageChange}
        onLimitChange={onLimitChange}
      />
    </div>
  );
}
