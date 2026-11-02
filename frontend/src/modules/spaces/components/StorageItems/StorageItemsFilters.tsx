import type { CategoryDTO } from "@/types";
import { TranslateFn } from "@/types/i18n";
import { Button } from "@/components/ui/Button";
import { ScrollRow } from "@/components/ui/ScrollRow";
import { CategoryAvatar } from "@/components/ui/CategoryAvatar";
import { categoryLabel } from "@/lib/i18nHelpers";

interface Props {
  t: TranslateFn;
  usedCategoriesData: CategoryDTO[];
  hasUncategorized: boolean;
  selectedCategoryId: string | null;
  onSelectCategory: (id: string | null) => void;
  itemCount: number;
}

export function StorageItemsFilters({
  t,
  usedCategoriesData,
  hasUncategorized,
  selectedCategoryId,
  onSelectCategory,
  itemCount,
}: Props) {
  if (itemCount === 0) return null;

  return (
    <ScrollRow
      role="group"
      aria-label={t("items:filterByCategory")}
      className="flex gap-2 pb-4 mb-2 -mx-4 px-4 sm:-mx-1 sm:px-1"
    >
      {/* `shrink-0 whitespace-nowrap` is what makes the row scroll instead of
          squashing the chips until a two-line label clips against the
          fixed-height button — which is what a shelf with many categories
          (the food seed has 16) looked like. */}
      <Button
        onClick={() => onSelectCategory("ALL")}
        variant={selectedCategoryId === "ALL" ? "default" : "outline"}
        className="shrink-0 whitespace-nowrap"
      >
        {t("common:filterAll")}
      </Button>
      {usedCategoriesData.map((cat: CategoryDTO) => (
        <Button
          key={cat.id}
          variant={selectedCategoryId === cat.id ? "secondary" : "outline"}
          onClick={() =>
            onSelectCategory(selectedCategoryId === cat.id ? "ALL" : cat.id)
          }
          className="shrink-0 whitespace-nowrap"
        >
          <div className="shrink-0">
            <CategoryAvatar category={cat} size="sm" />
          </div>
          <span>{categoryLabel(t, cat.code, cat.name)}</span>
        </Button>
      ))}
      {hasUncategorized && (
        <Button
          variant={selectedCategoryId === "NONE" ? "default" : "outline"}
          onClick={() =>
            onSelectCategory(selectedCategoryId === "NONE" ? "ALL" : "NONE")
          }
          className="shrink-0 whitespace-nowrap"
        >
          {t("items:noCategory")}
        </Button>
      )}
    </ScrollRow>
  );
}
