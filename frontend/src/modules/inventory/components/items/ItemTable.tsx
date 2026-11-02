import { Fragment, memo, useCallback, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useWindowVirtualizer } from "@tanstack/react-virtual";
import { Checkbox } from "@/components/ui/Checkbox";
import type { Item, CategoryDTO, StorageLocationSummary } from "@/types";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { ItemTableRow } from "./ItemTableRow";
import { ColumnProbe } from "./ColumnProbe";
import { groupItemsByCategory } from "./groupItemsByCategory";

/** Sort keys the list offers; only some of them have a column of their own. */
type ItemSortBy = "created_at" | "name" | "quantity" | "expiry_date";

/** Column key → the sort key that orders by it. */
const SORTABLE_COLUMNS: Record<string, ItemSortBy> = {
  product: "name",
  quantity: "quantity",
  expiry: "expiry_date",
};

interface ItemTableProps {
  items: Item[];
  storages?: StorageLocationSummary[];
  categories?: CategoryDTO[];
  enabledModules: string[];
  /** What the list is ordered by — reflected as `aria-sort` on that column. */
  sortBy?: ItemSortBy;
  sortOrder?: "asc" | "desc";
  /** Group rows under per-category header rows. Off by default. */
  groupByCategory?: boolean;
  onItemClick: (item: Item) => void;
  onConsume: (itemId: string) => void;
  onAddOne: (itemId: string) => void;
  onEdit: (itemId: string) => void;
  onDelete: (itemId: string) => void;
  onSetThreshold: (item: Item) => void;
  /** Whether to offer the per-row actions — all of them write. */
  canWrite?: boolean;
  /** Whether the rows may offer Delete — `items:delete`, a narrower key. */
  canDelete?: boolean;
  consumingId: string | null;
  selectedIds: string[];
  onToggleSelect: (id: string) => void;
  onSelectAll: (ids: string[]) => void;
}

/**
 * How wide the actions column has to be, derived rather than guessed.
 *
 * It was `9rem`, a round number nobody had checked against the row. Four 28px
 * icon buttons, three 4px gaps and a 9px divider come to 133px, and the cell
 * spends 32px of its own on padding — so the buttons overflowed 9px past the
 * column's left edge into the quantity beside them, leaving 7px between a
 * number and a bin icon. They read as one cluster because they were one.
 *
 * Adding a fifth action means changing `ACTION_BUTTONS` here, and
 * `ItemTableRow` has a test that fails if the two stop agreeing.
 */
export const ACTION_BUTTONS = 4;
const ACTION_BUTTON_PX = 28; // size="icon"
const ACTION_GAP_PX = 4; // gap-1
const ACTION_DIVIDER_PX = 9; // w-px + mx-1, before the destructive action
const ACTIONS_CELL_PADDING_PX = 32; // px-4 on both sides
const ACTIONS_COLUMN_PX =
  ACTION_BUTTONS * ACTION_BUTTON_PX +
  (ACTION_BUTTONS - 1) * ACTION_GAP_PX +
  ACTION_DIVIDER_PX +
  ACTIONS_CELL_PADDING_PX;
const ACTIONS_COLUMN_WIDTH = `${ACTIONS_COLUMN_PX}px`;

export default memo(function ItemTable({
  items,
  storages,
  categories,
  enabledModules,
  sortBy,
  sortOrder,
  groupByCategory = false,
  onItemClick,
  onConsume,
  onAddOne,
  onEdit,
  onDelete,
  onSetThreshold,
  consumingId,
  selectedIds,
  onToggleSelect,
  onSelectAll,
  canWrite = true,
  canDelete = canWrite,
}: ItemTableProps) {
  const { t } = useTranslation(["items", "categories", "common"]);

  const allSelected = items.length > 0 && selectedIds.length === items.length;

  // Auto-hide date columns when no visible item has data for them.
  // This prevents perpetually-empty columns for item types that don't use dates
  // (e.g. equipment assets, library books).
  const showFreezeDate = items.some((i) => i.freeze_date != null);
  const showExpiryDate = items.some((i) => i.expiry_date != null);

  // Column contributors registered by enabled modules. A contributor that
  // reports no value for any row on this page is dropped rather than rendered
  // as a column of blanks. When the answer needs a query the contributor says
  // so through a probe (`useHasValues`); the column stays out until the probe
  // answers, because an empty column is exactly what this avoids.
  //
  // An answer holds for the page it was given about. Carrying "yes" over to
  // the next page mounted that page's cells before its own answer was in, and
  // a cell that asks a question of its own asked it row by row.
  const allContributors = moduleRegistry.getColumnContributors(
    "items",
    enabledModules,
  );
  const pageKey = items.map((i) => i.id).join(",");
  const [probed, setProbed] = useState<
    Record<string, { pageKey: string; hasValues: boolean }>
  >({});
  const recordProbe = useCallback(
    (key: string, hasValues: boolean) => {
      setProbed((prev) =>
        prev[key]?.pageKey === pageKey && prev[key].hasValues === hasValues
          ? prev
          : { ...prev, [key]: { pageKey, hasValues } },
      );
    },
    [pageKey],
  );

  const contributors = allContributors.filter(
    ({ key, hasValue, useHasValues }) => {
      if (useHasValues)
        return probed[key]?.pageKey === pageKey && probed[key].hasValues;
      if (hasValue) return items.some(hasValue);
      return true;
    },
  );
  const extraBeforeName = contributors.filter(
    (c) => c.position === "after-name",
  );
  const extraBeforeActions = contributors.filter(
    (c) => c.position !== "after-name",
  );

  // Column widths, in the order the columns are rendered. A `<table>` has no
  // `fr` unit, so the flexible ones are handed to `table-fixed` as percentages
  // of the flexible total — the browser scales them against whatever the fixed
  // columns leave over, which is what `fr` did.
  const columnWidths = useMemo(() => {
    const specs: string[] = [
      "3rem",
      "2fr",
      ...extraBeforeName.map((c) => c.width ?? "1fr"),
      "1fr",
      "1fr",
      ...(showFreezeDate ? ["1fr"] : []),
      ...(showExpiryDate ? ["1fr"] : []),
      ...extraBeforeActions.map((c) => c.width ?? "1fr"),
      ACTIONS_COLUMN_WIDTH,
    ];
    const frOf = (spec: string) =>
      spec.endsWith("fr") ? parseFloat(spec) || 1 : null;
    const frTotal = specs.reduce((sum, s) => sum + (frOf(s) ?? 0), 0);
    return specs.map((s) => {
      const fr = frOf(s);
      if (fr === null) return s;
      return `${((fr / frTotal) * 100).toFixed(2)}%`;
    });
  }, [extraBeforeName, extraBeforeActions, showFreezeDate, showExpiryDate]);

  /** `aria-sort` for a column, or undefined when the list is ordered elsewhere. */
  const ariaSort = (columnKey: string) =>
    sortBy && SORTABLE_COLUMNS[columnKey] === sortBy
      ? sortOrder === "asc"
        ? ("ascending" as const)
        : ("descending" as const)
      : undefined;

  // The list scrolls with the page, not inside it: a scrollable box within a
  // scrollable page meant the wheel acted on whichever one the pointer
  // happened to be over, and touch gestures caught on the inner area.
  const listRef = useRef<HTMLTableSectionElement>(null);
  const useVirtual = items.length >= 50;

  const virtualizer = useWindowVirtualizer({
    count: items.length,
    estimateSize: () => 48,
    overscan: 10,
    enabled: useVirtual,
    scrollMargin: listRef.current?.offsetTop ?? 0,
  });

  // Sticky on the cells, not on `<thead>`: with `border-separate` the section
  // element is not a sticky containing block in every browser, the cells are.
  // Column headings survived the first scroll as text; the point is that they
  // survive it on screen too, now that the list scrolls with the page.
  const headerCellClass =
    "sticky top-0 z-10 bg-surface px-4 py-2 border-b border-border";

  const virtualRows = virtualizer.getVirtualItems();
  const paddingTop = virtualRows.length
    ? virtualRows[0].start - virtualizer.options.scrollMargin
    : 0;
  const paddingBottom = virtualRows.length
    ? virtualizer.getTotalSize() -
      (virtualRows[virtualRows.length - 1].end -
        virtualizer.options.scrollMargin)
    : 0;

  const rowCommonProps = {
    canWrite,
    canDelete,
    onItemClick,
    onConsume,
    onAddOne,
    onEdit,
    onDelete,
    onSetThreshold,
    onToggleSelect,
    consumingId,
    showFreezeDate,
    showExpiryDate,
    extraBeforeName,
    extraBeforeActions,
    storages,
    categories,
  };

  // Grouped view: rows sit under a per-category header that names the
  // group and counts its rows on this page. The windowed path below indexes
  // rows by position, which interleaved headers would break — grouping and
  // virtualization do not mix, and a page is at most a few hundred rows, so
  // the grouped table renders unwindowed.
  const groups = useMemo(
    () =>
      groupByCategory
        ? groupItemsByCategory(items, categories, t("common:noCategory"), t)
        : null,
    [groupByCategory, items, categories, t],
  );

  return (
    <div className="hidden lg:block">
      {allContributors
        .filter((c) => c.useHasValues)
        .map((c) => (
          <ColumnProbe
            key={c.key}
            columnKey={c.key}
            useHasValues={c.useHasValues!}
            items={items}
            onResult={recordProbe}
          />
        ))}

      <table className="w-full table-fixed border-separate border-spacing-y-0">
        <colgroup>
          {columnWidths.map((width, i) => (
            <col key={i} style={{ width }} />
          ))}
        </colgroup>
        <thead>
          <tr className="text-xs font-medium uppercase tracking-wider text-on-muted">
            <th scope="col" className={`${headerCellClass} text-left`}>
              <Checkbox
                checked={allSelected}
                onChange={() =>
                  onSelectAll(allSelected ? [] : items.map((i) => i.id))
                }
                className="w-4 h-4 text-accent-600 focus:ring-accent-500"
                aria-label={t("common:actions.selectAll", {
                  defaultValue: "Select all",
                })}
              />
            </th>
            <th
              scope="col"
              aria-sort={ariaSort("product")}
              className={`${headerCellClass} text-left`}
            >
              {t("table.product")}
            </th>
            {extraBeforeName.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={`${headerCellClass} text-left`}
              >
                {t(c.label)}
              </th>
            ))}
            <th scope="col" className={`${headerCellClass} text-left`}>
              {t("table.location")}
            </th>
            <th
              scope="col"
              aria-sort={ariaSort("quantity")}
              className={`${headerCellClass} text-right`}
            >
              {t("table.quantity")}
            </th>
            {showFreezeDate && (
              <th scope="col" className={`${headerCellClass} text-left`}>
                {t("table.freezeDate")}
              </th>
            )}
            {showExpiryDate && (
              <th
                scope="col"
                aria-sort={ariaSort("expiry")}
                className={`${headerCellClass} text-left`}
              >
                {t("table.expiryDate")}
              </th>
            )}
            {extraBeforeActions.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={`${headerCellClass} text-left`}
              >
                {t(c.label)}
              </th>
            ))}
            <th scope="col" className={`${headerCellClass} text-right pr-4`}>
              {t("table.actions")}
            </th>
          </tr>
        </thead>
        <tbody ref={listRef}>
          {groups ? (
            groups.map((group) => (
              <Fragment key={group.key}>
                <tr>
                  <td
                    colSpan={columnWidths.length}
                    className="px-4 pt-4 pb-1.5 border-b border-border"
                  >
                    <div className="flex items-center gap-2">
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
                  </td>
                </tr>
                {group.items.map((item) => (
                  <ItemTableRow
                    key={item.id}
                    item={item}
                    isSelected={selectedIds.includes(item.id)}
                    {...rowCommonProps}
                  />
                ))}
              </Fragment>
            ))
          ) : useVirtual ? (
            <>
              {/* Virtualisation by spacer rows rather than absolute
                  positioning: a `<tr>` taken out of flow stops being a row of
                  this table, both for layout and for a screen reader. */}
              {paddingTop > 0 && (
                <tr aria-hidden="true" style={{ height: paddingTop }}>
                  <td colSpan={columnWidths.length} />
                </tr>
              )}
              {virtualRows.map((virtualRow) => (
                <ItemTableRow
                  key={items[virtualRow.index].id}
                  item={items[virtualRow.index]}
                  isSelected={selectedIds.includes(items[virtualRow.index].id)}
                  {...rowCommonProps}
                />
              ))}
              {paddingBottom > 0 && (
                <tr aria-hidden="true" style={{ height: paddingBottom }}>
                  <td colSpan={columnWidths.length} />
                </tr>
              )}
            </>
          ) : (
            items.map((item) => (
              <ItemTableRow
                key={item.id}
                item={item}
                isSelected={selectedIds.includes(item.id)}
                {...rowCommonProps}
              />
            ))
          )}
        </tbody>
      </table>
    </div>
  );
});
