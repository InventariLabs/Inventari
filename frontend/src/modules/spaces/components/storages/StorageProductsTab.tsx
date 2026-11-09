import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { extractApiError } from "@/lib/errors";
import { toast } from "sonner";
import { DeleteReasonDialog } from "@/modules/inventory/moduleApi";
import { Checkbox } from "@/components/ui/Checkbox";
import { InlineQueryError } from "@/components/ui/QueryResult";
import LoadingSpinner from "@/components/LoadingSpinner";
import StorageItemsSection from "@/modules/spaces/components/StorageItemsSection";
import {
  useConsumeItemFromStorage,
  useDeleteItemFromStorage,
} from "@/modules/spaces/hooks/useStorageItemMutations";
import { useStorageItems } from "@/modules/shared/hooks/useStorages";
import { useAllCategories } from "@/modules/shared/hooks/useCategories";
import { useLocationsInside } from "@/modules/spaces/hooks/useLocationsInside";
import { toAmount } from "@/utils/formatters";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import type { Item, StorageLocation, StorageLocationSummary } from "@/types";
import StorageItemModals from "./StorageItemModals";

/** A consume answer is finished when the record left or nothing remains. */
const consumeFinished = (updatedItem: Item): boolean =>
  updatedItem.is_deleted || (toAmount(updatedItem.quantity) ?? 0) <= 0;

interface StorageProductsTabProps {
  storage: StorageLocation;
  /** The row the detail pane reads this place from. */
  summary: StorageLocationSummary;
  isArchived: boolean;
  canWriteItems: boolean;
  /** Leave out the records of a module, as the counts next to it do. */
  excludeModuleContexts?: boolean;
}

function InsideNote({ summary }: { summary: StorageLocationSummary }) {
  const { t } = useTranslation("locations");
  const count = useLocationsInside(summary);
  return (
    <p className="text-xs text-on-muted">
      {t("products.includingInside", { count })}
    </p>
  );
}

/**
 * The products of one location — and, when the reader asks, of everything
 * standing inside it.
 *
 * The old detail page could only list what stood directly on the shelf, so a
 * warehouse's own products were invisible from the warehouse while its
 * zones each kept their own tally. "Include locations inside" is the same
 * list with the subtrees appended, each row still the product record it
 * always was.
 */
export function StorageProductsTab({
  storage,
  summary,
  isArchived,
  canWriteItems,
  excludeModuleContexts = false,
}: StorageProductsTabProps) {
  const { t } = useTranslation([
    "locations",
    "categories",
    "items",
    "common",
    "labels",
  ]);
  const [deletingItem, setDeletingItem] = useState<Item | null>(null);
  const [editingItemId, setEditingItemId] = useState<string | null>(null);
  const [actionItem, setActionItem] = useState<Item | null>(null);
  const [includeInside, setIncludeInside] = useState(false);

  // What stands inside is read when the reader asks to see it: one request
  // for the place and everything below it, not one per place.
  const {
    data: allItems,
    isLoading,
    isPlaceholderData,
    isError,
    error,
    refetch,
  } = useStorageItems(storage.id, includeInside, excludeModuleContexts);
  // Ticking the box keeps the place's own rows up while the wider answer is
  // on its way. They are not the list the box asked for, so the tab says it
  // is still reading rather than show part of the list as the whole of it.
  const readingInside = includeInside && isPlaceholderData;
  const { data: categories } = useAllCategories();

  const [selectedCategoryId, setSelectedCategoryId] = useState<string | null>(
    "ALL",
  );

  const usedCategoryIds = useMemo(() => {
    if (!allItems) return [];
    const ids = new Set(
      allItems.map((item) => item.category_id).filter(Boolean),
    );
    return Array.from(ids);
  }, [allItems]);

  const usedCategoriesData = useMemo(() => {
    if (!categories) return [];
    return categories
      .filter((category) => usedCategoryIds.includes(category.id))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [categories, usedCategoryIds]);

  const hasUncategorized = useMemo(
    () => allItems?.some((item) => !item.category_id) || false,
    [allItems],
  );

  useEffect(() => {
    if (!allItems || !selectedCategoryId || selectedCategoryId === "ALL")
      return;
    const stillOnTheShelf =
      selectedCategoryId === "NONE"
        ? hasUncategorized
        : usedCategoryIds.includes(selectedCategoryId);
    if (stillOnTheShelf) return;
    setSelectedCategoryId("ALL");
    toast.info(t("items:messages.categoryFilterCleared"));
  }, [allItems, selectedCategoryId, usedCategoryIds, hasUncategorized, t]);

  const filteredItems = useMemo(() => {
    if (!allItems) return [];
    if (selectedCategoryId === "ALL") return allItems;
    if (selectedCategoryId === "NONE")
      return allItems.filter((item) => !item.category_id);
    return allItems.filter((item) => item.category_id === selectedCategoryId);
  }, [allItems, selectedCategoryId]);

  const deleteItemMutation = useDeleteItemFromStorage(storage.id);

  const consumeItemMutation = useConsumeItemFromStorage(storage.id);
  const consumeMutation = {
    mutate: (itemId: string) =>
      consumeItemMutation.mutate(
        { itemId, quantity: 1 },
        {
          onSuccess: (updatedItem) => {
            if (consumeFinished(updatedItem)) {
              toast.success(
                t("common:messages.success", {
                  defaultValue: "Item consumed!",
                }),
              );
            } else {
              // What was taken and what remains are two numbers; the old
              // message put the remainder where the amount taken belongs.
              toast.success(
                t("items:quickActions.consumedSuccessRemaining", {
                  remaining: formatQuantityLocalized(
                    t,
                    updatedItem.quantity,
                    updatedItem.uom?.symbol,
                    updatedItem.uom?.rounding,
                  ),
                }),
              );
            }
          },
          onError: (error: unknown) => {
            toast.error(extractApiError(error, "Failed to remove from stock"));
          },
        },
      ),
    isPending: consumeItemMutation.isPending,
    variables: consumeItemMutation.variables,
  };

  if (isLoading) {
    return <LoadingSpinner />;
  }

  if (isError) {
    return <InlineQueryError error={error} onRetry={() => void refetch()} />;
  }

  return (
    <div className="space-y-4">
      {summary.direct_children_count > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 px-1">
          <Checkbox
            id="include-inside"
            label={t("locations:products.includeInside")}
            checked={includeInside}
            onChange={(event) => setIncludeInside(event.target.checked)}
          />
          {includeInside && <InsideNote summary={summary} />}
        </div>
      )}

      {readingInside ? (
        <LoadingSpinner />
      ) : (
        <StorageItemsSection
          t={t}
          canWriteItems={canWriteItems}
          storageId={storage.id}
          isArchived={isArchived}
          behaviorMode={storage.location_type?.behavior_mode}
          filteredItems={filteredItems}
          items={allItems}
          usedCategoriesData={usedCategoriesData}
          hasUncategorized={hasUncategorized}
          selectedCategoryId={selectedCategoryId}
          onSelectCategory={setSelectedCategoryId}
          onItemClick={setActionItem}
          onConsumeItem={(itemId) => consumeMutation.mutate(itemId)}
          onEditItem={setEditingItemId}
          onDeleteItem={setDeletingItem}
          isConsumePending={consumeMutation.isPending}
          consumePendingId={consumeMutation.variables?.itemId}
          isDeletePending={deleteItemMutation.isPending}
        />
      )}

      <StorageItemModals
        editingItemId={editingItemId}
        setEditingItemId={setEditingItemId}
        actionItem={actionItem}
        setActionItem={setActionItem}
      />

      <DeleteReasonDialog
        key={deletingItem?.id ?? "no-delete"}
        open={deletingItem !== null}
        itemName={deletingItem?.name ?? ""}
        onConfirm={async (reason, notes) => {
          // Awaited, so a refused delete leaves the dialog standing with the
          // reason and note as typed.
          if (deletingItem)
            await deleteItemMutation.mutateAsync({
              itemId: deletingItem.id,
              reason,
              notes,
            });
          setDeletingItem(null);
        }}
        onCancel={() => setDeletingItem(null)}
      />
    </div>
  );
}
