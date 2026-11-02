import { Plus, Settings2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { SearchableCombobox } from "@/components/ui/SearchableCombobox";
import { categoryLabel } from "@/lib/i18nHelpers";
import type { CategoryDTO } from "@/types";

interface CategoryFieldProps {
  /** Trigger id, so the renderer's `<label htmlFor>` names this control. */
  id?: string;
  value: unknown;
  categories: CategoryDTO[];
  onChange: (value: unknown) => void;
  onAddCategory?: () => void;
  /** Open the CategoryFormModal to edit field_definitions. */
  onConfigureCategoryFields?: (categoryId: string) => void;
}

export function CategoryField({
  id,
  value,
  categories,
  onChange,
  onAddCategory,
  onConfigureCategoryFields,
}: CategoryFieldProps) {
  const { t } = useTranslation(["items", "categories", "common", "modules"]);
  const stringVal = String(value ?? "");
  const selectedCategory = categories.find((c) => c.id === stringVal);

  const categoryOptions = categories.map((cat) => ({
    id: cat.id,
    name: categoryLabel(t, cat.code, cat.name),
    icon: cat.icon ?? undefined,
  }));

  // What the module owning this category is called — the registry has the
  // category's tag, the translation catalogues have its name. The raw value
  // is the fallback for a module without an entry, not a silent blank.
  const owningModuleName = (() => {
    const owner =
      selectedCategory?.module_name ?? selectedCategory?.context_tag ?? "";
    return owner
      ? t(`modules.${owner}.name`, { ns: "modules", defaultValue: owner })
      : "";
  })();

  return (
    <div className="space-y-3">
      <SearchableCombobox
        id={id}
        options={categoryOptions}
        value={stringVal}
        onChange={onChange}
        // A product without a category is a normal state — the products list
        // filters by it. Without this the picker could only swap one category
        // for another, so a category given by accident could never be taken
        // back off the record.
        clearable
        clearLabel={t("items:noCategory")}
        placeholder={t("items:bulkEdit.selectCategory", {
          defaultValue: "Select category",
        })}
        searchPlaceholder={t("common:search", {
          defaultValue: "Search...",
        })}
        emptyMessage={t("common:noResults")}
        title={t("items:bulkEdit.selectCategory", {
          defaultValue: "Select category",
        })}
      />
      {selectedCategory?.is_module_owned && (
        <p
          className="rounded-lg bg-amber-50 p-2.5 text-xs leading-relaxed text-on-warning"
          data-testid="category-module-warning"
        >
          {t("items:categoryModuleWarning", {
            category: categoryLabel(
              t,
              selectedCategory.code,
              selectedCategory.name,
            ),
            module: owningModuleName,
          })}
        </p>
      )}
      {onConfigureCategoryFields && selectedCategory && (
        <Button
          size="content"
          type="button"
          variant="ghost"
          onClick={() => onConfigureCategoryFields(selectedCategory.id)}
          className="w-full h-9 rounded-lg border border-border text-on-muted hover:text-primary-600 hover:border-primary-200 gap-2 text-xs"
          data-testid="configure-category-fields"
        >
          <Settings2 size={14} />
          {t("items:bulkEdit.configureCategoryFields")}
        </Button>
      )}
      {onAddCategory && (
        <Button
          size="content"
          type="button"
          variant="ghost"
          onClick={onAddCategory}
          className="w-full h-9 rounded-lg border border-dashed border-border text-on-muted hover:text-primary-600 hover:border-primary-200 gap-2 text-xs"
        >
          <Plus size={14} />
          {t("categories:addCategory", {
            defaultValue: "Add new category",
          })}
        </Button>
      )}
    </div>
  );
}
