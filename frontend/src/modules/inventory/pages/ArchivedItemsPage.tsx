import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { categoryLabel } from "@/lib/i18nHelpers";
import { useNavigate } from "react-router-dom";
import { Archive, RotateCcw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { ListControlBar } from "@/components/ui/ListControlBar";
import LoadingSpinner from "@/components/LoadingSpinner";
import { Pagination } from "@/module-sdk";
import { Textarea } from "@/components/ui/Textarea";
import { QueryResult } from "@/components/ui/QueryResult";
import {
  useRestoreItem,
  usePurgeItem,
} from "@/modules/inventory/hooks/useItemMutations";
import { useArchivedItems } from "@/modules/inventory/hooks/useItems";
import { archivedReasonLabel } from "@/modules/shared/lib/archiveReasons";
import { useArchiveTabs } from "@/hooks/useArchiveTabs";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useFilteredList } from "@/hooks/useFilteredList";
import { useHasPermission } from "@/hooks/useHasPermission";
import { useKeysetPaging } from "@/hooks/useKeysetPaging";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import {
  useOrganization,
  useShowModuleData,
} from "@/modules/settings/hooks/useOrganization";
import { formatDate } from "@/utils/helpers";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 50;

/** The product list's own cell geometry, so the two tables read as one table
 *  showing the same records in two states. */
const headerCell = "bg-surface px-4 py-2 border-b border-border";
const bodyCell = "px-4 py-2 align-middle border-b border-border";

/** Business profiles that start with permanent deletion locked (mirrors the
 * backend resolver in items/_lifecycle.py). */
const PURGE_LOCKED_PROFILES = ["equipment_wms", "clean_core"];

/** Effective allow_permanent_delete: explicit setting wins, otherwise the
 *  product profile decides; legacy orgs without a profile stay allowed. */
function resolveAllowPermanentDelete(
  org:
    | {
        settings?: Record<string, unknown> | null;
        active_profile_id?: string | null;
      }
    | null
    | undefined,
): boolean {
  const flag = org?.settings?.allow_permanent_delete;
  if (typeof flag === "boolean") {
    return flag;
  }
  return !PURGE_LOCKED_PROFILES.includes(org?.active_profile_id ?? "");
}

/** Columns that give way below `sm`: five columns of a table are wider than
 *  a phone, and the way back (Restore) sat in the one that fell off the right
 *  edge. The reason stays; the date moves under the name. */
const wideOnly = "hidden sm:table-cell";

const REASON_COLORS: Record<string, string> = {
  USED: "bg-primary-100 text-primary-800",
  DISPOSED: "bg-red-100 text-red-800",
  EXPIRED: "bg-amber-100 text-amber-800",
  DAMAGED: "bg-red-100 text-red-800",
  LOST: "bg-surface-raised text-on",
  RETIRED: "bg-purple-100 text-purple-800",
  TEST_DATA: "bg-teal-100 text-teal-800",
  OTHER: "bg-slate-100 text-slate-700",
  // Written by module flows (equipment register, storage archive) rather
  // than by a person naming a reason — a neutral state, not a judgement.
  ARCHIVED: "bg-surface-raised text-on",
};

/** Normalize the DB ``deletion_reason`` (lowercase in requests, UPPERCASE
 *  in locale keys) to the UPPERCASE key form. */
function reasonKey(reason: string): string {
  return reason.toUpperCase();
}

/** The product's name and, under it, what was written when it was deleted.
 *  The archive is where restoring or purging is decided, so the note from the
 *  delete dialog is read here. Below `sm` the date also lives under the name,
 *  since its own column is hidden there. */
function ArchivedNameCell({
  name,
  note,
  deletedAt,
}: {
  name: string;
  note?: string | null;
  deletedAt?: string | null;
}) {
  const { t } = useTranslation("items");
  return (
    <>
      <span className="text-sm font-semibold text-on [overflow-wrap:anywhere] block sm:truncate">
        {name}
      </span>
      {note && (
        <span className="mt-0.5 block text-xs text-on-secondary [overflow-wrap:anywhere]">
          <span className="font-medium">{t("archivedNoteLabel")}:</span> {note}
        </span>
      )}
      {deletedAt && (
        <span className="mt-0.5 block text-xs text-on-secondary tabular-nums sm:hidden">
          {formatDate(deletedAt)}
        </span>
      )}
    </>
  );
}

/** One page of the archive and the bar that turns it. The archive only grows,
 *  so the server pages it by the last row seen: the next page is asked for
 *  with the cursor the page on screen carried, and a new question (the
 *  phrase, the module-data policy) starts again from its first page. */
function useArchivePage(search: string, excludeModuleContexts: boolean) {
  const question = useMemo(
    () => ({
      search: search || undefined,
      exclude_module_contexts: excludeModuleContexts,
    }),
    [search, excludeModuleContexts],
  );
  const paging = useKeysetPaging(question);
  const archivedQuery = useArchivedItems({
    ...question,
    limit: PAGE_SIZE,
    cursor: paging.cursor,
  });
  const page = archivedQuery.data;
  return {
    archivedQuery,
    pagination: {
      skip: paging.page * PAGE_SIZE,
      limit: PAGE_SIZE,
      total: page?.total ?? 0,
      keyset: {
        rows: page?.items?.length ?? 0,
        hasNext: Boolean(page?.next_cursor),
      },
      onPrev: paging.goPrev,
      // The cursor on screen belongs to the page it came with; while the next
      // page loads the old rows are still shown, and their cursor must not be
      // taken for the new page's.
      onNext: () => {
        if (!archivedQuery.isPlaceholderData) paging.goNext(page?.next_cursor);
      },
    },
  };
}

export default function ArchivedItemsPage() {
  const navigate = useNavigate();
  const { t } = useTranslation(["items", "common"]);
  const { setHeader } = useModulePageHeader();
  // The same debounced search the active list runs on — the phrase goes to
  // the server, so a match on a later page answers.
  const f = useFilteredList({}, { searchDebounceMs: 400 });
  // The archive is the active list in another state, so it follows the same
  // module-data policy — a restore is confirmed on the tab the row reappears
  // on, and two tabs of one screen must describe one population.
  const excludeModuleContexts = !useShowModuleData();
  const { archivedQuery, pagination } = useArchivePage(
    f.search,
    excludeModuleContexts,
  );
  const items = archivedQuery.data?.items ?? [];
  const total = pagination.total;
  const restoreMutation = useRestoreItem();
  const purgeMutation = usePurgeItem();
  const { data: org } = useOrganization();
  // Two different questions, and until now the screen asked only the first.
  // `allow_permanent_delete` is the organization's policy; `items:purge` and
  // `items:write` are this account's rights, which the API checks on the other
  // end. Offered without them, both buttons ended in a 403 after the click.
  const allowPermanentDelete = resolveAllowPermanentDelete(org);
  const canRestore = useCanWrite("items");
  const mayPurge = useHasPermission("items:purge");
  const canPurge = allowPermanentDelete && mayPurge;
  const showActions = canRestore || canPurge;

  const [purgeTarget, setPurgeTarget] = useState<string | null>(null);
  const [purgeReason, setPurgeReason] = useState("");
  const [restoreTarget, setRestoreTarget] = useState<string | null>(null);

  const handleRestore = (itemId: string) => {
    restoreMutation.mutate(itemId, {
      onSuccess: () => {
        toast.success(t("items:itemRestored"));
        setRestoreTarget(null);
      },
    });
  };

  const handlePurge = (itemId: string) => {
    purgeMutation.mutate(
      { itemId, reason: purgeReason.trim() || undefined },
      {
        onSuccess: () => {
          toast.success(t("items:itemPurged"));
          setPurgeTarget(null);
          setPurgeReason("");
        },
      },
    );
  };

  const restoreItem = items?.find((i) => i.id === restoreTarget);

  // The same pair of tabs the active list carries — the archive is that list
  // in another state, and the way back has to be where the way in was.
  const archiveTabs = useArchiveTabs("archived", (tab) => {
    if (tab === "active") navigate("/inventory/items");
  });

  // The archive is no longer a tab in the module's navigation, so the shell
  // has no nav item to read a title from — the page names itself.
  useEffect(() => {
    setHeader({
      title: t("items:archivedItems"),
      backTo: "/inventory/items",
    });
  }, [setHeader, t]);

  return (
    <div className="space-y-6">
      {/* The active list has a search and a filter; this one had neither, over
          sixty rows whose names repeat. The search bar survives an empty
          answer — it is the only way to widen the list back. */}
      {total > 0 || f.isNarrowed ? (
        <ListControlBar
          primaryTabs={archiveTabs}
          search={{
            value: f.searchInput,
            onChange: f.setSearchInput,
            placeholder: t("items:archivedSearchPlaceholder"),
          }}
        />
      ) : (
        <ListControlBar primaryTabs={archiveTabs} />
      )}
      <QueryResult
        query={archivedQuery}
        loadingFallback={
          <div className="flex items-center justify-center h-64">
            <LoadingSpinner />
          </div>
        }
      >
        {(data) => {
          // The server narrows the archive; what came back is what shows.
          const archivedItems = data?.items ?? [];
          if (f.search && archivedItems.length === 0) {
            return (
              <EmptyState
                icon={Archive}
                title={t("items:archivedNoMatches")}
                description={t("items:archivedNoMatchesDesc")}
                primaryAction={
                  <Button variant="link" onClick={() => f.setSearchInput("")}>
                    {t("common:actions.clear")}
                  </Button>
                }
              />
            );
          }
          if (archivedItems.length === 0) {
            return (
              <EmptyState
                icon={Archive}
                title={t("items:noArchivedItems")}
                description={
                  // "You can restore or permanently remove them" over an
                  // archive whose only button is Restore: permanent removal is
                  // an organization setting, and it is off by default. An
                  // account that may not write products has neither.
                  !canRestore
                    ? t("items:noArchivedItemsDescViewOnly")
                    : allowPermanentDelete
                      ? t("items:noArchivedItemsDesc")
                      : t("items:noArchivedItemsDescRestoreOnly")
                }
                primaryAction={
                  <Button
                    variant="link"
                    onClick={() => navigate("/inventory/items")}
                  >
                    {t("items:backToActiveItems")}
                  </Button>
                }
              />
            );
          }
          /* The archive is a list of records, so it is a `<table>` (§14.1) —
             and the same table the product list is, since it is the same
             records in another state. It was a stack of `div` rows with the
             values unlabelled, and its actions were the only labelled buttons
             on any list in the product. */
          return (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs font-medium uppercase tracking-wider text-on-muted">
                    <th scope="col" className={headerCell + " text-left"}>
                      {t("items:table.product")}
                    </th>
                    <th
                      scope="col"
                      className={cn(headerCell, "text-left", wideOnly)}
                    >
                      {t("items:table.category")}
                    </th>
                    <th scope="col" className={headerCell + " text-left"}>
                      {t("items:archivedReasonLabel")}
                    </th>
                    <th
                      scope="col"
                      className={cn(headerCell, "text-left", wideOnly)}
                    >
                      {t("items:archivedDeletedAtLabel")}
                    </th>
                    {showActions && (
                      <th scope="col" className={headerCell + " text-right"}>
                        {t("items:table.actions")}
                      </th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {archivedItems.map((item) => (
                    <tr key={item.id} className="group">
                      <td className={bodyCell}>
                        <ArchivedNameCell
                          name={item.name}
                          note={item.deletion_notes}
                          deletedAt={item.deleted_at}
                        />
                      </td>
                      <td
                        className={cn(bodyCell, "text-on-secondary", wideOnly)}
                      >
                        {item.category
                          ? categoryLabel(
                              t,
                              item.category.code,
                              item.category.name,
                            )
                          : "—"}
                      </td>
                      <td className={bodyCell}>
                        {item.deletion_reason ? (
                          <Badge
                            className={
                              REASON_COLORS[reasonKey(item.deletion_reason)] ??
                              REASON_COLORS.OTHER
                            }
                          >
                            {archivedReasonLabel(t, item.deletion_reason)}
                          </Badge>
                        ) : (
                          <span className="text-on-muted">
                            {archivedReasonLabel(t, null)}
                          </span>
                        )}
                      </td>
                      <td
                        className={cn(
                          bodyCell,
                          "text-on-secondary tabular-nums",
                          wideOnly,
                        )}
                      >
                        {item.deleted_at ? formatDate(item.deleted_at) : "—"}
                      </td>
                      {showActions && (
                        <td className={bodyCell}>
                          {/* Two icons, the shape every other list uses. Each
                            carries `aria-label` and `title` with the same
                            words (§11.4), and the destructive one is divided
                            off and coloured at rest (§2.13a). */}
                          <div className="flex items-center justify-end gap-1">
                            {canRestore && (
                              <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => setRestoreTarget(item.id)}
                                disabled={restoreMutation.isPending}
                                aria-label={t("items:restoreItem")}
                                title={t("items:restoreItem")}
                              >
                                <RotateCcw size={16} />
                              </Button>
                            )}
                            {canPurge && (
                              <>
                                {/* The rule divides the destructive action
                                    from the safe one; with no safe one to
                                    divide from it is a stray line. */}
                                {canRestore && (
                                  <span
                                    aria-hidden="true"
                                    className="w-px h-5 shrink-0 bg-border mx-1"
                                  />
                                )}
                                <Button
                                  variant="ghostDanger"
                                  size="icon"
                                  onClick={() => {
                                    setPurgeTarget(item.id);
                                    setPurgeReason("");
                                  }}
                                  disabled={purgeMutation.isPending}
                                  aria-label={t("items:purgeItem")}
                                  title={t("items:purgeItem")}
                                >
                                  <Trash2 size={16} />
                                </Button>
                              </>
                            )}
                          </div>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }}
      </QueryResult>

      <Pagination {...pagination} />

      <ConfirmDialog
        open={restoreTarget !== null}
        title={t("items:confirmRestore")}
        message={restoreItem ? restoreItem.name : ""}
        confirmLabel={t("items:restoreItem")}
        cancelLabel={t("common:actions.cancel")}
        variant="default"
        onConfirm={() => restoreTarget && handleRestore(restoreTarget)}
        onCancel={() => setRestoreTarget(null)}
      />

      {allowPermanentDelete && (
        <ConfirmDialog
          open={purgeTarget !== null}
          title={t("items:confirmPurge")}
          message={t("items:confirmPurgeMsg")}
          confirmLabel={t("items:purgeItem")}
          cancelLabel={t("common:actions.cancel")}
          variant="danger"
          onConfirm={() => purgeTarget && handlePurge(purgeTarget)}
          onCancel={() => {
            setPurgeTarget(null);
            setPurgeReason("");
          }}
        >
          <Textarea
            wrapperClassName="mt-3"
            label={t("items:purgeReasonLabel")}
            id="purge-reason"
            value={purgeReason}
            onChange={(e) => setPurgeReason(e.target.value)}
            placeholder={t("items:purgeReasonPlaceholder")}
            rows={2}
            className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-on placeholder:text-on-muted focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
        </ConfirmDialog>
      )}
    </div>
  );
}
