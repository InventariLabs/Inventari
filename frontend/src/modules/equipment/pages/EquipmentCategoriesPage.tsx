import { useState, useMemo, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Pencil, Trash2, Monitor } from "lucide-react";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { Button } from "@/components/ui/Button";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { EmptyState } from "@/components/ui/EmptyState";
import { QueryError } from "@/components/ui/QueryResult";
import LoadingSpinner from "@/components/LoadingSpinner";
import { CategoryAvatar } from "@/components/ui/CategoryAvatar";
import { getCategoryLabel } from "@/modules/equipment/components/assetUtils";
import { CategoryFormModal } from "@/modules/inventory/moduleApi";
import { useConfirm } from "@/hooks/useConfirm";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import {
  useCategories,
  useDeleteCategory,
} from "@/modules/shared/hooks/useCategories";
import type { CategoryDTO } from "@/types";

export default function EquipmentCategoriesPage() {
  const { t } = useTranslation(["equipment", "common"]);
  const { setHeader } = useModulePageHeader();
  // Categories are Core, and `categories:write` is the key the API will check
  // on the other end of these buttons — asking about `equipment:write` here
  // would gate the screen on a right that has nothing to do with the answer.
  const canWrite = useCanWrite("categories");

  const {
    data: allCategories = [],
    isLoading,
    isError,
    refetch,
    // With counts: the number that decides whether a category can be deleted
    // is how much is filed under it, and the card was showing how many custom
    // fields it declares — a fact about the form, not about the register.
  } = useCategories(undefined, undefined, true);
  const deleteMutation = useDeleteCategory();
  const { confirm, confirmDialogProps } = useConfirm();

  const equipmentCategories = useMemo(
    () =>
      allCategories.filter((c: CategoryDTO) => c.context_tag === "equipment"),
    [allCategories],
  );

  const [showModal, setShowModal] = useState(false);
  const [editingCategory, setEditingCategory] = useState<CategoryDTO | null>(
    null,
  );

  useEffect(() => {
    setHeader({
      actions: canWrite ? (
        <div className="ml-auto">
          <Button
            leftIcon={<Plus size={16} />}
            onClick={() => {
              setEditingCategory(null);
              setShowModal(true);
            }}
          >
            {t("categories.add", "Add Category")}
          </Button>
        </div>
      ) : undefined,
    });
  }, [t, setHeader, canWrite]);

  const handleEdit = (cat: CategoryDTO) => {
    setEditingCategory(cat);
    setShowModal(true);
  };

  const handleDelete = async (cat: CategoryDTO) => {
    const ok = await confirm({
      title: t("categories.deleteTitle", "Delete category"),
      // The name the list calls this record by: built-in categories are
      // seeded in English and the interface translates them by code, so a
      // raw `cat.name` asks "delete Desktop Computer?" under a row that
      // reads "Komputer stacjonarny".
      message: t("categories.confirmDelete", {
        name: getCategoryLabel(t, { code: cat.code, name: cat.name }),
      }),
      variant: "danger",
      confirmLabel: t("common:actions.delete"),
    });
    if (!ok) return;
    deleteMutation.mutate(cat.id);
  };

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="categories" />
      {/* List */}
      {isError ? (
        <QueryError onRetry={() => refetch()} />
      ) : isLoading ? (
        <LoadingSpinner />
      ) : equipmentCategories.length === 0 ? (
        <EmptyState
          icon={Monitor}
          title={t("categories.empty", "No equipment categories yet")}
          description={t("categories.emptyDescription")}
        />
      ) : (
        /* A list of records is a `<table>` (§14.1). These rows have columns —
           a name, a code, two counts, actions — and a stack of cards gave a
           sighted reader those columns while giving a screen reader none of
           them: no cell tied to a heading, no table navigation, nowhere to
           put `aria-sort`. The table is the DESKTOP list; §14.1 keeps a phone
           card branch beside it, because the alternative was a scroller with
           no signal, and the edit and delete buttons lived one swipe off the
           right edge at 390px. */
        <>
          <div className="hidden md:block relative overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs font-medium uppercase tracking-wider text-on-muted">
                  <th scope="col" className="px-4 py-2 text-left">
                    {t("categories.table.name", "Category")}
                  </th>
                  <th scope="col" className="px-4 py-2 text-left">
                    {t("categories.table.code", "Code")}
                  </th>
                  <th scope="col" className="px-4 py-2 text-right">
                    {t("categories.table.assets", "Assets")}
                  </th>
                  <th scope="col" className="px-4 py-2 text-right">
                    {t("categories.table.fields", "Fields")}
                  </th>
                  {canWrite && (
                    <th scope="col" className="px-4 py-2 text-right">
                      {t("common:actions.title", "Actions")}
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {equipmentCategories.map((cat: CategoryDTO) => {
                  const fieldCount = (cat.field_definitions ?? []).filter(
                    (f) => f.visible !== false,
                  ).length;
                  // The same words the row shows, so the button that acts on
                  // this record is announced by the name the reader just read.
                  const label = getCategoryLabel(t, {
                    code: cat.code,
                    name: cat.name,
                  });
                  return (
                    <tr key={cat.id} className="border-b border-border">
                      <td className="px-4 py-2">
                        <div className="flex items-center gap-3 min-w-0">
                          <CategoryAvatar
                            category={cat}
                            size="md"
                            shape="square"
                          />
                          <span className="text-sm font-semibold text-on truncate">
                            {label}
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-2 font-mono text-xs text-on-muted">
                        {cat.code || "—"}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums text-on-secondary">
                        {cat.items_count ?? 0}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums text-on-secondary">
                        {fieldCount}
                      </td>
                      {canWrite && (
                        <td className="px-4 py-2">
                          <div className="flex items-center justify-end gap-1">
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleEdit(cat)}
                              aria-label={t("common:a11y.editNamed", {
                                name: label,
                              })}
                              title={t("common:actions.edit")}
                            >
                              <Pencil size={16} />
                            </Button>
                            <Button
                              variant="ghostDanger"
                              size="icon"
                              onClick={() => handleDelete(cat)}
                              disabled={deleteMutation.isPending}
                              aria-label={t("common:a11y.deleteNamed", {
                                name: label,
                              })}
                              title={t("common:actions.delete")}
                            >
                              <Trash2 size={16} />
                            </Button>
                          </div>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {/* The same records below `md`, one card each: the table stays the
           desktop list, and the actions the scroller used to push off the
           right edge sit in the row a thumb reaches. */}
          <ul className="md:hidden divide-y divide-border">
            {equipmentCategories.map((cat: CategoryDTO) => {
              const fieldCount = (cat.field_definitions ?? []).filter(
                (f) => f.visible !== false,
              ).length;
              const label = getCategoryLabel(t, {
                code: cat.code,
                name: cat.name,
              });
              return (
                <li key={cat.id} className="py-3 flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-3 min-w-0">
                      <CategoryAvatar category={cat} size="md" shape="square" />
                      <span className="text-sm font-semibold text-on truncate">
                        {label}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-on-muted">
                      {t("categories.table.code", "Code")}:{" "}
                      {cat.code || "\u2014"} {"\u00b7"}{" "}
                      {t("categories.table.assets", "Assets")}:{" "}
                      {cat.items_count ?? 0} {"\u00b7"}{" "}
                      {t("categories.table.fields", "Fields")}: {fieldCount}
                    </p>
                  </div>
                  {canWrite && (
                    <div className="flex items-center gap-1 shrink-0">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleEdit(cat)}
                        aria-label={t("common:a11y.editNamed", { name: label })}
                        title={t("common:actions.edit")}
                      >
                        <Pencil size={16} />
                      </Button>
                      <Button
                        variant="ghostDanger"
                        size="icon"
                        onClick={() => handleDelete(cat)}
                        disabled={deleteMutation.isPending}
                        aria-label={t("common:a11y.deleteNamed", {
                          name: label,
                        })}
                        title={t("common:actions.delete")}
                      >
                        <Trash2 size={16} />
                      </Button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}

      {/* Modal — reuses the inventory CategoryFormModal */}
      <CategoryFormModal
        key={editingCategory?.id ?? "new"}
        isOpen={showModal}
        editingCategory={editingCategory}
        contextTag="equipment"
        groupSuggestions={Array.from(
          new Set(
            allCategories
              .map((cat) => cat.group_label)
              .filter((g): g is string => Boolean(g)),
          ),
        ).sort()}
        onClose={() => {
          setShowModal(false);
          setEditingCategory(null);
        }}
      />
      <ConfirmDialog {...confirmDialogProps} />
    </div>
  );
}
