import type { CategoryDTO, Item } from "@/types";
import { TranslateFn } from "@/types/i18n";
import { categoryLabel } from "@/lib/i18nHelpers";
import { StorageItemsFilters } from "./StorageItems/StorageItemsFilters";
import { StorageItemsTable } from "./StorageItems/StorageItemsTable";
import { StorageItemsCards } from "./StorageItems/StorageItemsCards";
import { StorageItemsEmpty } from "./StorageItems/StorageItemsEmpty";

type Props = {
  t: TranslateFn;
  storageId: string;
  isArchived?: boolean;
  /** ``StorageType.behavior_mode`` of the location's type. */
  behaviorMode?: string;
  filteredItems: Item[];
  items: Item[] | undefined;
  usedCategoriesData: CategoryDTO[];
  hasUncategorized: boolean;
  selectedCategoryId: string | null;
  onSelectCategory: (id: string | null) => void;
  onItemClick: (item: Item) => void;
  onConsumeItem: (itemId: string) => void;
  onEditItem: (itemId: string) => void;
  onDeleteItem: (item: Item) => void;
  /** Whether the reader may change the products sitting here. */
  canWriteItems?: boolean;
  isConsumePending: boolean;
  consumePendingId: string | undefined;
  isDeletePending: boolean;
};

export default function StorageItemsSection({
  t,
  storageId,
  isArchived,
  behaviorMode,
  filteredItems,
  items,
  usedCategoriesData,
  hasUncategorized,
  selectedCategoryId,
  onSelectCategory,
  onItemClick,
  onConsumeItem,
  onEditItem,
  onDeleteItem,
  canWriteItems = true,
  isConsumePending,
  consumePendingId,
  isDeletePending,
}: Props) {
  // The name reads two serializations of a category — the nested schema on
  // an item and the list DTO — so the parameter keeps to what both share:
  // the code and the name. The id is the fallback key either way.
  const getCategoryName = (
    cat: { name: string; code?: string | null } | undefined | null,
    categoryId: string | null | undefined,
  ): string => {
    if (!categoryId) return t("items:noCategory");
    if (!cat) return t("items:unknown");
    return categoryLabel(t, cat.code, cat.name);
  };

  return (
    <div>
      <h2 className="text-lg font-semibold text-on mb-4 px-1">
        {t("locations:detail.products", { count: filteredItems?.length || 0 })}
      </h2>

      <StorageItemsFilters
        t={t}
        usedCategoriesData={usedCategoriesData}
        hasUncategorized={hasUncategorized}
        selectedCategoryId={selectedCategoryId}
        onSelectCategory={onSelectCategory}
        itemCount={items?.length || 0}
      />

      {filteredItems && filteredItems.length > 0 ? (
        <>
          <StorageItemsTable
            t={t}
            canWriteItems={canWriteItems}
            filteredItems={filteredItems}
            behaviorMode={behaviorMode}
            onItemClick={onItemClick}
            onConsumeItem={onConsumeItem}
            onEditItem={onEditItem}
            onDeleteItem={onDeleteItem}
            isConsumePending={isConsumePending}
            consumePendingId={consumePendingId}
            isDeletePending={isDeletePending}
            getCategoryName={getCategoryName}
          />

          <StorageItemsCards
            t={t}
            canWriteItems={canWriteItems}
            filteredItems={filteredItems}
            onItemClick={onItemClick}
            onConsumeItem={onConsumeItem}
            isConsumePending={isConsumePending}
            consumePendingId={consumePendingId}
            getCategoryName={getCategoryName}
          />
        </>
      ) : (
        <StorageItemsEmpty
          t={t}
          storageId={storageId}
          isArchived={isArchived}
          canWriteItems={canWriteItems}
        />
      )}
    </div>
  );
}
