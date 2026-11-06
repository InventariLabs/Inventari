import { useState, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { categoryLabel } from "@/lib/i18nHelpers";
import { Link, useNavigate } from "react-router-dom";
import {
  Plus,
  Tag,
  Edit2,
  Trash2,
  ArchiveRestore,
  FolderPen,
  SearchX,
  X,
  EyeOff,
  Settings,
} from "lucide-react";
import LoadingSpinner from "@/components/LoadingSpinner";
import Button from "@/components/ui/Button";
import { EmptyState, EmptyStateAction } from "@/components/ui/EmptyState";
import { InlineQueryError, QueryError } from "@/components/ui/QueryResult";
import { ListControlBar, RowLabel } from "@/components/ui/ListControlBar";
import { Select } from "@/components/ui/Select";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { CategoryAvatar } from "@/components/ui/CategoryAvatar";
import { Pagination } from "@/module-sdk";
import { usePagination } from "@/hooks/usePagination";
import type { CategoryDTO } from "@/types";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";
import { useConfirm } from "@/hooks/useConfirm";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import {
  useCategories,
  useHiddenCategoryCount,
  useUpdateCategory,
  useDeleteCategory,
} from "@/modules/shared/hooks/useCategories";
import { useShowModuleData } from "@/modules/settings/hooks/useOrganization";
import {
  categoryGroup,
  categoryGroupLabel,
  categoryGroups,
} from "@/modules/inventory/utils/categoryGroups";
import { CategoryFormModal } from "@/modules/inventory/components/CategoryFormModal";
import { CategoryGroupSheet } from "@/modules/inventory/components/CategoryGroupSheet";
import { HiddenRecordsNotice } from "@/modules/shared/components/HiddenRecordsNotice";

/**
 * The three empties of a filtered list, told apart: a filter that
 * found nothing offers the way back, an organisation without categories yet
 * is offered its first one, and a list the module-data policy narrowed to
 * zero says how many it keeps out — naming the switch, not claiming "none".
 * Asking to create a duplicate of something the filter is hiding was the old
 * single answer to all three.
 */
function EmptyCategories({
  filtersActive,
  onClearFilters,
  onAdd,
  canWrite,
  hiddenCount = 0,
}: {
  filtersActive: boolean;
  onClearFilters: () => void;
  onAdd: () => void;
  /** Whether to offer the first category, or only say there is none yet. */
  canWrite: boolean;
  /** Categories the module-data policy keeps off this list; 0 = not probed. */
  hiddenCount?: number;
}) {
  const { t } = useTranslation("categories");
  const navigate = useNavigate();
  if (filtersActive) {
    return (
      <EmptyState
        icon={SearchX}
        title={t("empty.noResultsTitle")}
        description={t("empty.noResultsSubtitle")}
        primaryAction={
          <EmptyStateAction
            label={t("empty.clearFilters")}
            onClick={onClearFilters}
            leftIcon={X}
          />
        }
      />
    );
  }
  if (hiddenCount > 0) {
    return (
      <EmptyState
        icon={EyeOff}
        title={t("hidden.title")}
        description={t("hidden.description", { count: hiddenCount })}
        primaryAction={
          <EmptyStateAction
            label={t("hidden.openSettings")}
            // The anchor lands on the module-data switch, not the page top.
            onClick={() => navigate("/settings#module-data")}
            leftIcon={Settings}
          />
        }
      />
    );
  }
  return (
    <EmptyState
      icon={Tag}
      title={t("empty.title")}
      description={t("empty.subtitle")}
      primaryAction={
        canWrite ? (
          <EmptyStateAction
            // Outline: the header's add is the view's one filled action.
            variant="outline"
            label={t("addButton")}
            onClick={onAdd}
            leftIcon={Plus}
          />
        ) : undefined
      }
    />
  );
}

/** The card's two mutations, each reporting its own outcome as a toast. */
function useCategoryCardMutations() {
  const { t } = useTranslation("categories");
  const updateCategoryMutation = useUpdateCategory();
  const deleteCategoryMutation = useDeleteCategory();

  const deleteMutation = {
    mutate: (id: string) =>
      deleteCategoryMutation.mutate(id, {
        onSuccess: () => toast.success(t("messages.deleted")),
        onError: (error: unknown) =>
          toast.error(extractApiError(error, t("messages.deleteError"))),
      }),
  };

  const restoreMutation = {
    mutate: (id: string) =>
      updateCategoryMutation.mutate(
        { id, data: { is_active: true } },
        {
          onSuccess: () =>
            toast.success(
              t("messages.restored", { defaultValue: "Category restored" }),
            ),
          onError: (err) =>
            toast.error(
              extractApiError(
                err,
                t("messages.restoreError", {
                  defaultValue: "Error restoring category",
                }),
              ),
            ),
        },
      ),
  };

  return { deleteMutation, restoreMutation };
}

function ManageGroupButton({ onClick }: { onClick: () => void }) {
  const { t } = useTranslation("categories");
  return (
    <Button
      variant="ghost"
      size="iconSm"
      onClick={onClick}
      title={t("groups_manage.manage")}
      aria-label={t("groups_manage.manage")}
    >
      <FolderPen size={16} />
    </Button>
  );
}

export default function CategoriesPage() {
  const { t } = useTranslation(["categories", "common"]);
  const { setHeader } = useModulePageHeader();
  // Categories are a Core register, so the key the API checks is the
  // register's own — not the module the reader happens to have arrived from.
  const canWrite = useCanWrite("categories");
  const [search, setSearch] = useState("");
  const { confirm, confirmDialogProps } = useConfirm();
  const [groupFilter, setGroupFilter] = useState<string>("ALL");
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingCategory, setEditingCategory] = useState<CategoryDTO | null>(
    null,
  );
  // The group the reader is looking at, opened for renaming. A group is a
  // label repeated on its categories, so this is the one place it can be
  // changed without opening every category that carries it.
  const [managingGroup, setManagingGroup] = useState<string | null>(null);

  useEffect(() => {
    setHeader({
      // The categories register has no navigation entry of its own, so the
      // shell cannot fall back to a nav item's title — the page names itself.
      title: t("title"),
      actions: canWrite ? (
        <div className="ml-auto">
          <Button
            onClick={() => {
              setEditingCategory(null);
              setIsModalOpen(true);
            }}
            leftIcon={<Plus size={16} />}
          >
            {t("addButton")}
          </Button>
        </div>
      ) : undefined,
    });
  }, [t, setHeader, canWrite]);

  // Counts come from the list endpoint: a card that cannot say how much the
  // category holds is a coloured label and nothing more.
  //
  // The module filter used to be hard-coded on here — the one list where the
  // organization policy ("Module data in general lists") had no effect, so
  // eight equipment categories were unreachable at every setting.
  const excludeModuleContexts = !useShowModuleData();
  const {
    data: categories,
    isLoading,
    isError,
    refetch,
  } = useCategories(true, excludeModuleContexts, true);

  // The probe the products list runs: a policy-narrowed zero must not read
  // as "no categories" — the reader who believed it met the existing one as
  // a duplicate-name refusal at save time.
  const filtersActive = search.trim() !== "" || groupFilter !== "ALL";
  const hidden = useHiddenCategoryCount(
    excludeModuleContexts,
    isLoading,
    categories?.length,
    filtersActive,
  );

  const { deleteMutation, restoreMutation } = useCategoryCardMutations();

  const filteredCategories = categories?.filter((cat) => {
    // The reader searches for what the card shows — the translated name —
    // and the record's own name still matches for a code-less category.
    const query = search.toLowerCase();
    const matchesSearch =
      cat.name.toLowerCase().includes(query) ||
      categoryLabel(t, cat.code, cat.name).toLowerCase().includes(query);
    const matchesGroup =
      groupFilter === "ALL" || categoryGroup(cat) === groupFilter;
    return matchesSearch && matchesGroup;
  });

  // 76 categories in one uninterrupted grid is a scroll with no landmarks.
  // The page size is the reader's to choose, on the same terms the products
  // list offers — one module, one contract about how its lists move.
  const [pageSize, setPageSize] = useState(24);
  const { skip, limit, onPrev, onNext, setPage } = usePagination(
    filteredCategories?.length ?? 0,
    pageSize,
  );
  const visibleCategories = filteredCategories?.slice(skip, skip + limit);
  const totalCategories = filteredCategories?.length ?? 0;

  /** Filter options from the distinct groups actually present in the data. */
  const groupOptions = useMemo(
    () => categoryGroups(categories ?? []),
    [categories],
  );

  const groupLabel = (group: string): string => categoryGroupLabel(t, group);

  if (isLoading) return <LoadingSpinner />;
  // Without this the failed request rendered "add your first category" over a
  // dictionary of thirty-eight, and the reader obliged with a duplicate.
  if (isError) return <QueryError onRetry={refetch} />;

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="categories" />
      <ListControlBar
        search={{
          value: search,
          onChange: setSearch,
          placeholder: t("searchPlaceholder"),
        }}
        // A Select, not a tab row: tabs read well at three values and fall
        // apart at ten, and groups are meant to be as many as the
        // organisation needs. Same layout as the location filter on the
        // reorder rules page — full-width search, filter at its end.
        primaryAction={
          <>
            <RowLabel>{t("filterGroupLabel")}</RowLabel>
            <div className="w-52">
              <Select
                // The RowLabel beside the trigger belongs to the row, not to
                // this control — the trigger names itself.
                aria-label={t("filterGroupLabel")}
                value={groupFilter}
                onChange={setGroupFilter}
                placeholder={t("filterAllGroups")}
                options={[
                  { id: "ALL", name: t("filterAllGroups") },
                  ...groupOptions.map((group) => ({
                    id: group,
                    name: groupLabel(group),
                  })),
                ]}
              />
            </div>
            {/* The group being looked at is the group that can be changed.
                Without this, renaming one meant opening each of its
                categories in turn — a dozen or more for a seeded group. */}
            {groupFilter !== "ALL" && canWrite && (
              <ManageGroupButton
                onClick={() => setManagingGroup(groupFilter)}
              />
            )}
          </>
        }
      />

      {hidden.isError && (
        <InlineQueryError error={hidden.error} onRetry={hidden.refetch} />
      )}
      {visibleCategories && visibleCategories.length > 0 ? (
        <>
          {/* The hidden counter belongs to the list, not to its empty state
              (same finding as the products list): rows in view must not
              silence it. Same shared notice, this list's own wording. */}
          {hidden.count > 0 && (
            <HiddenRecordsNotice
              message={t("hidden.inlineCount", { count: hidden.count })}
              actionLabel={t("hidden.openSettings")}
            />
          )}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
            {visibleCategories.map((category) => (
              <article
                key={category.id}
                className={`group relative flex flex-col items-center gap-2 overflow-hidden rounded-2xl border border-border p-4 text-center shadow-sm transition-all hover:shadow-md active:scale-95 ${
                  category.is_active === false
                    ? "bg-surface-raised opacity-60 grayscale"
                    : "bg-surface-card"
                }`}
              >
                <div className="text-2xl transition-transform group-hover:scale-110">
                  <CategoryAvatar
                    category={{
                      ...category,
                      contextTag: category.context_tag,
                    }}
                    size="lg"
                    shape="circle"
                  />
                </div>
                <div className="min-w-0 w-full">
                  <h3 className="truncate text-sm font-semibold text-on">
                    {categoryLabel(t, category.code, category.name)}
                  </h3>
                  {category.items_count != null && (
                    // The count was the only thing on the card that knew where
                    // its products are, and it was not a way to get to them.
                    <Link
                      to={`/inventory/items?category_id=${category.id}`}
                      className="mt-0.5 inline-flex min-h-11 items-center text-xs text-on-secondary hover:underline md:min-h-0"
                      aria-label={t("itemsCountAria", {
                        count: category.items_count,
                      })}
                    >
                      <span className="font-semibold tabular-nums text-on">
                        {category.items_count}
                      </span>{" "}
                      {t("itemsCount", { count: category.items_count })}
                    </Link>
                  )}
                </div>
                {/* Always reachable: hover is not a thing on a phone, and a
                  keyboard user needs the buttons the moment they are tabbed
                  to. On a pointer device they still fade in on hover. */}
                {canWrite && (
                  <div className="absolute right-1 top-1 flex gap-0.5 transition-opacity focus-within:opacity-100 group-hover:opacity-100 lg:right-2 lg:top-2 lg:opacity-0">
                    <Button
                      size="icon"
                      variant="ghost"
                      onClick={() => {
                        setEditingCategory(category);
                        setIsModalOpen(true);
                      }}
                      className="bg-surface-card/90"
                      aria-label={t("actions.edit", { ns: "common" })}
                    >
                      <Edit2 size={12} />
                    </Button>
                    {category.is_active === false ? (
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => {
                          restoreMutation.mutate(category.id);
                        }}
                        className="bg-surface-card/90"
                        aria-label={t("actions.restore", {
                          defaultValue: "Restore",
                        })}
                        title={t("actions.restore", {
                          defaultValue: "Restore",
                        })}
                      >
                        <ArchiveRestore size={12} />
                      </Button>
                    ) : (
                      <Button
                        size="icon"
                        variant="ghostDanger"
                        onClick={async () => {
                          // The number stands on the card beside this button, so
                          // the confirmation is the place to say what it means:
                          // a used category cannot be deleted at all (the backend
                          // refuses while any product points here), an empty one
                          // goes away for good.
                          const count = category.items_count;
                          // A non-zero count is the refusal already known: the
                          // message names the repair, and an active red button
                          // that could only answer 400 is not offered.
                          const blocked = count != null && count > 0;
                          const message =
                            count == null
                              ? t("messages.confirmDelete")
                              : blocked
                                ? t("messages.confirmDeleteWithCount", {
                                    count,
                                  })
                                : t("messages.confirmDeleteEmpty");
                          if (
                            await confirm({
                              title: t("actions.delete", { ns: "common" }),
                              message,
                              variant: "danger",
                              confirmLabel: t("actions.delete", {
                                ns: "common",
                              }),
                              cancelLabel: blocked
                                ? t("actions.close", { ns: "common" })
                                : undefined,
                              hideConfirm: blocked,
                            })
                          ) {
                            deleteMutation.mutate(category.id);
                          }
                        }}
                        className="bg-surface-card/90"
                        aria-label={t("actions.delete", { ns: "common" })}
                        title={t("actions.delete", { ns: "common" })}
                      >
                        <Trash2 size={12} />
                      </Button>
                    )}
                  </div>
                )}
              </article>
            ))}
          </div>
        </>
      ) : (
        <EmptyCategories
          canWrite={canWrite}
          filtersActive={filtersActive}
          hiddenCount={hidden.count}
          onClearFilters={() => {
            setSearch("");
            setGroupFilter("ALL");
          }}
          onAdd={() => {
            setEditingCategory(null);
            setIsModalOpen(true);
          }}
        />
      )}

      {totalCategories > pageSize && (
        <Pagination
          skip={skip}
          limit={limit}
          total={totalCategories}
          onPrev={onPrev}
          onNext={onNext}
          onPageChange={(next) => setPage(next - 1)}
          onLimitChange={(next) => {
            setPageSize(next);
            setPage(0);
          }}
          pageSizeOptions={[24, 48, 96, 200]}
        />
      )}

      {/* Add/Edit Modal */}
      <CategoryFormModal
        isOpen={isModalOpen}
        editingCategory={editingCategory}
        groupSuggestions={Array.from(
          new Set(
            (categories ?? [])
              .map((cat) => cat.group_label)
              .filter((g): g is string => Boolean(g)),
          ),
        ).sort()}
        onClose={() => {
          setIsModalOpen(false);
          setEditingCategory(null);
        }}
      />
      {managingGroup && (
        <CategoryGroupSheet
          group={managingGroup}
          onClose={() => setManagingGroup(null)}
          onDone={(newName) => {
            setGroupFilter(newName ?? "ALL");
            setManagingGroup(null);
          }}
        />
      )}

      <ConfirmDialog {...confirmDialogProps} />
    </div>
  );
}
