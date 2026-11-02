import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { MoveRight, PackageOpen, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { EmptyState, EmptyStateAction } from "@/components/ui/EmptyState";
import LoadingSpinner from "@/components/LoadingSpinner";
import { Pagination } from "@/module-sdk";
import { QueryError } from "@/components/ui/QueryResult";
import {
  CHILDREN_PAGE_SIZE,
  useStorageChildren,
} from "@/modules/spaces/hooks/useStorageChildren";
import type { StorageLocationSummary } from "@/types";

interface StorageContentsTabProps {
  parent: Pick<StorageLocationSummary, "id" | "items_count">;
  /** Whether the organization keeps module-owned places out of the lists. */
  excludeModuleContexts: boolean;
  canWrite: boolean;
  onSelect: (id: string) => void;
  /** Opens the move picker with these locations. */
  onMove: (ids: string[]) => void;
  onShowProducts: () => void;
}

/**
 * What stands directly inside the selected location.
 *
 * A table rather than the grid of identical cards the zone page had
 * (UI_GUIDELINES §14.1): five things per row — name, code, type, what is
 * inside it and how many products — read as columns, and a row is the way
 * into that location. A leaf says plainly that it has nothing inside and
 * points at the tab where its products are, instead of offering an empty
 * table that reads as a broken screen.
 */
export function StorageContentsTab({
  parent,
  excludeModuleContexts,
  canWrite,
  onSelect,
  onMove,
  onShowProducts,
}: StorageContentsTabProps) {
  const { t } = useTranslation(["locations", "common"]);
  const [checked, setChecked] = useState<Set<string>>(() => new Set());
  const [skip, setSkip] = useState(0);
  useEffect(() => setSkip(0), [parent.id]);
  const { data, isLoading, isError, refetch } = useStorageChildren(parent.id, {
    excludeModuleContexts,
    skip,
  });
  const children = data?.items ?? [];
  // A checked location that has moved away, or belongs to a location no
  // longer selected, is not in this table — so it is not part of the action.
  const selected = new Set(
    children.map((child) => child.id).filter((id) => checked.has(id)),
  );

  const toggle = (id: string) =>
    setChecked(() => {
      const next = new Set(selected);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  if (isLoading) return <LoadingSpinner />;
  if (isError) return <QueryError onRetry={() => void refetch()} />;

  if (children.length === 0) {
    return (
      <EmptyState
        icon={PackageOpen}
        title={t("locations:contents.emptyTitle")}
        description={t("locations:contents.emptyDescription", {
          count: parent.items_count,
        })}
        primaryAction={
          <EmptyStateAction
            label={t("locations:contents.showProducts")}
            onClick={onShowProducts}
          />
        }
      />
    );
  }

  const rowFor = (child: StorageLocationSummary) => ({
    id: child.id,
    name: child.name,
    code: child.short_code,
    type: child.location_type?.name,
    inside: child.direct_children_count,
    products: child.subtree_items_count,
  });

  return (
    <div className="space-y-3">
      {canWrite && selected.size > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl bg-surface-inset px-3 py-2">
          <span className="text-sm text-on-secondary">
            {t("locations:contents.selected", { count: selected.size })}
          </span>
          <Button
            size="sm"
            onClick={() => onMove([...selected])}
            leftIcon={<MoveRight size={16} />}
          >
            {t("locations:reorg.moveTo")}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setChecked(new Set())}
            leftIcon={<X size={16} />}
          >
            {t("locations:contents.clearSelection")}
          </Button>
        </div>
      )}

      {/* Desktop: columns. */}
      <div className="relative hidden overflow-x-auto rounded-xl border border-border sm:block">
        <table className="w-full table-fixed text-sm">
          <thead className="bg-surface-inset text-left text-xs uppercase tracking-wide text-on-muted">
            <tr>
              {canWrite && (
                <th scope="col" className="w-10 px-3 py-2">
                  <span className="sr-only">
                    {t("locations:contents.selectColumn")}
                  </span>
                </th>
              )}
              <th scope="col" className="px-3 py-2">
                {t("locations:contents.name")}
              </th>
              <th scope="col" className="w-[14%] px-3 py-2">
                {t("locations:contents.code")}
              </th>
              <th scope="col" className="w-[18%] px-3 py-2">
                {t("locations:contents.type")}
              </th>
              <th scope="col" className="w-[12%] px-3 py-2 text-right">
                {t("locations:contents.inside")}
              </th>
              <th scope="col" className="w-[12%] px-3 py-2 text-right">
                {t("locations:contents.products")}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {children.map((child) => {
              const row = rowFor(child);
              return (
                <tr
                  key={row.id}
                  className="cursor-pointer hover:bg-surface-raised"
                  onClick={() => onSelect(row.id)}
                >
                  {canWrite && (
                    <td
                      className="px-3 py-2.5"
                      onClick={(event) => event.stopPropagation()}
                    >
                      <Checkbox
                        aria-label={t("locations:contents.selectRow", {
                          name: row.name,
                        })}
                        checked={selected.has(row.id)}
                        onChange={() => toggle(row.id)}
                      />
                    </td>
                  )}
                  <td className="px-3 py-2.5">
                    <Button
                      variant="ghost"
                      size="inline"
                      className="max-w-full truncate text-left text-sm font-medium text-on hover:underline"
                      onClick={(event) => {
                        event.stopPropagation();
                        onSelect(row.id);
                      }}
                    >
                      {row.name}
                    </Button>
                  </td>
                  <td className="px-3 py-2.5 font-mono text-xs text-on-secondary">
                    {row.code ?? "—"}
                  </td>
                  <td className="truncate px-3 py-2.5 text-xs text-on-secondary">
                    {row.type ?? "—"}
                  </td>
                  <td className="px-3 py-2.5 text-right text-xs tabular-nums text-on-secondary">
                    {row.inside}
                  </td>
                  <td className="px-3 py-2.5 text-right text-xs tabular-nums text-on-secondary">
                    {row.products}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Phone: the same rows as full-width targets. */}
      <ul className="divide-y divide-border rounded-xl border border-border sm:hidden">
        {children.map((child) => {
          const row = rowFor(child);
          return (
            <li key={row.id} className="flex items-center gap-3">
              {canWrite && (
                <label
                  htmlFor={`location-select-${row.id}`}
                  className="flex min-w-11 self-stretch cursor-pointer items-center justify-center"
                >
                  <Checkbox
                    id={`location-select-${row.id}`}
                    aria-label={t("locations:contents.selectRow", {
                      name: row.name,
                    })}
                    checked={selected.has(row.id)}
                    onChange={() => toggle(row.id)}
                  />
                </label>
              )}
              <Button
                variant="ghost"
                size="row"
                onClick={() => onSelect(row.id)}
                className="min-w-0 flex-1 justify-between"
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium text-on">
                    {row.name}
                  </span>
                  <span className="block truncate text-xs text-on-muted">
                    {[row.code, row.type].filter(Boolean).join(" · ") || "—"}
                  </span>
                </span>
                <span className="shrink-0 text-right">
                  <span className="block text-sm tabular-nums text-on">
                    {row.products}
                  </span>
                  <span className="block text-[10px] text-on-muted">
                    {t("locations:card.unit", { count: row.products })}
                  </span>
                </span>
              </Button>
            </li>
          );
        })}
      </ul>

      {(data?.total ?? 0) > CHILDREN_PAGE_SIZE && (
        <Pagination
          skip={skip}
          limit={CHILDREN_PAGE_SIZE}
          total={data?.total ?? 0}
          onPrev={() => setSkip((s) => Math.max(s - CHILDREN_PAGE_SIZE, 0))}
          onNext={() => setSkip((s) => s + CHILDREN_PAGE_SIZE)}
        />
      )}
    </div>
  );
}
