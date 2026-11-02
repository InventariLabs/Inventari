import { useRef, type ComponentPropsWithRef, type CSSProperties } from "react";
import { useTranslation } from "react-i18next";
import { useWindowVirtualizer } from "@tanstack/react-virtual";
import { ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { cn } from "@/lib/utils";
import { formatQuantityLocale } from "@/utils/formatters";
import type { LookupFailure } from "@/modules/warehouse/hooks/useOccupancyLookups";
import { AverageFill } from "./AverageFill";
import { FillBar } from "./FillBar";
import {
  hitQuantity,
  hitsAt,
  onlyProduct,
  statusTone,
  type HitsByLocation,
  type OccupancyEntry,
  type OccupancyNode,
} from "./occupancyModel";

/** From this many rows the tree draws only the ones in view. */
export const VIRTUALISE_FROM = 100;
const LOCATION_ROW = 44;
const PRODUCT_ROW = 36;

type TrProps = ComponentPropsWithRef<"tr">;

type TreeRow =
  | { kind: "location"; node: OccupancyNode }
  | { kind: "product"; node: OccupancyNode; entry: OccupancyEntry }
  | { kind: "failure"; node: OccupancyNode; failure: LookupFailure };

interface OccupancyTreeProps {
  /** The rows after the filter and the folds, in walk order. */
  nodes: OccupancyNode[];
  folded: Set<string>;
  /** Shelves whose products are listed under them. */
  opened: Set<string>;
  /** Every product of each opened shelf, once its own read has answered. */
  entries: Map<string, OccupancyEntry[]>;
  /** Opened shelves whose own read failed. */
  failures: Map<string, LookupFailure>;
  hits: HitsByLocation;
  onToggleFold: (id: string) => void;
  onToggleOpen: (id: string) => void;
  onOpenSettings: (node: OccupancyNode) => void;
}

/**
 * The location rows plus the product rows of every opened mixed shelf — or,
 * where the shelf's read failed, a row that says so.
 */
function toRows(
  nodes: OccupancyNode[],
  opened: Set<string>,
  entries: Map<string, OccupancyEntry[]>,
  failures: Map<string, LookupFailure>,
): TreeRow[] {
  return nodes.flatMap((node): TreeRow[] => {
    const row: TreeRow = { kind: "location", node };
    if (!node.cell || !opened.has(node.location_id)) return [row];
    const failure = failures.get(node.location_id);
    if (failure) return [row, { kind: "failure", node, failure }];
    const listed = entries.get(node.location_id);
    if (!listed) return [row];
    return [
      row,
      ...listed
        .filter((entry) => Number(entry.quantity) > 0 || entry.share !== null)
        .map((entry): TreeRow => ({ kind: "product", node, entry })),
    ];
  });
}

/**
 * Every warehouse, zone and shelf as one table: the walk order down the page,
 * a fill bar where a location has a limit, a summary where it holds others.
 *
 * Long lists are drawn with spacer rows, not absolute positioning — a row
 * taken out of flow stops being a row of its table, for layout and for a
 * screen reader — and the page scrolls, not a box inside it.
 */
export function OccupancyTree(props: OccupancyTreeProps) {
  const { t } = useTranslation("warehouse");
  const rows = toRows(props.nodes, props.opened, props.entries, props.failures);
  const bodyRef = useRef<HTMLTableSectionElement>(null);
  const virtual = rows.length >= VIRTUALISE_FROM;

  const virtualizer = useWindowVirtualizer({
    count: rows.length,
    estimateSize: (index) =>
      rows[index].kind === "location" ? LOCATION_ROW : PRODUCT_ROW,
    overscan: 12,
    enabled: virtual,
    scrollMargin: bodyRef.current?.offsetTop ?? 0,
  });
  const items = virtual ? virtualizer.getVirtualItems() : [];
  // A row is as tall as what it says — a second line for an unmeasured shelf, a
  // stacked summary on a phone — so a drawn row reports its real height.
  const shown = virtual
    ? items.map((item) => ({
        row: rows[item.index],
        trProps: {
          "data-index": item.index,
          ref: virtualizer.measureElement,
        } as TrProps,
      }))
    : rows.map((row) => ({ row, trProps: {} as TrProps }));
  const paddingTop = items.length
    ? items[0].start - virtualizer.options.scrollMargin
    : 0;
  const paddingBottom = items.length
    ? virtualizer.getTotalSize() -
      (items[items.length - 1].end - virtualizer.options.scrollMargin)
    : 0;

  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-surface-card">
      <table className="w-full text-sm">
        <thead className="hidden bg-surface-raised text-left text-xs font-medium text-on-secondary md:table-header-group">
          <tr>
            <th scope="col" className="px-4 py-2.5">
              {t("occupancy.columns.location")}
            </th>
            <th scope="col" className="px-4 py-2.5">
              {t("occupancy.columns.occupancy")}
            </th>
            <th scope="col" className="hidden px-4 py-2.5 md:table-cell">
              {t("occupancy.columns.contents")}
            </th>
            <th scope="col" className="hidden px-4 py-2.5 md:table-cell">
              {t("occupancy.columns.walkOrder")}
            </th>
          </tr>
        </thead>
        <tbody ref={bodyRef} className="divide-y divide-border">
          {paddingTop > 0 && (
            <tr aria-hidden="true" style={{ height: paddingTop }}>
              <td colSpan={4} />
            </tr>
          )}
          {shown.map(({ row, trProps }) =>
            row.kind === "location" ? (
              <LocationRow
                key={row.node.location_id}
                node={row.node}
                trProps={trProps}
                {...props}
              />
            ) : row.kind === "failure" ? (
              <FailureRow
                key={`${row.node.location_id}:failure`}
                node={row.node}
                failure={row.failure}
                trProps={trProps}
              />
            ) : (
              <ProductRow
                key={`${row.node.location_id}:${row.entry.product_template_id}`}
                node={row.node}
                entry={row.entry}
                trProps={trProps}
              />
            ),
          )}
          {paddingBottom > 0 && (
            <tr aria-hidden="true" style={{ height: paddingBottom }}>
              <td colSpan={4} />
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/** The one line a location row says about what is inside it. */
function contentsText(
  node: OccupancyNode,
  t: ReturnType<typeof useTranslation>["t"],
): string {
  const { summary, cell } = node;
  if (summary) {
    const parts = [
      t("occupancy.summary.locations", { count: summary.shelves }),
      t("occupancy.summary.withLimit", { count: summary.with_limit }),
    ];
    if (summary.full > 0) {
      parts.push(t("occupancy.summary.full", { count: summary.full }));
    }
    if (summary.empty > 0) {
      parts.push(t("occupancy.summary.empty", { count: summary.empty }));
    }
    return parts.join(" · ");
  }
  if (!cell) return "";
  if (cell.products === 0) return t("occupancy.empty");
  const only = onlyProduct(cell);
  if (only) {
    return `${formatQuantityLocale(only.quantity)} ${only.product_unit_symbol ?? ""} · ${only.product_template_name ?? ""}`;
  }
  return t("occupancy.products", { count: cell.products });
}

function LocationRow({
  node,
  folded,
  opened,
  hits: found,
  onToggleFold,
  onToggleOpen,
  onOpenSettings,
  trProps,
}: OccupancyTreeProps & { node: OccupancyNode; trProps: TrProps }) {
  const { t } = useTranslation("warehouse");
  const { cell, summary } = node;
  const isFolded = folded.has(node.location_id);
  const isOpened = opened.has(node.location_id);
  const mixed = (cell?.products ?? 0) > 1;
  const canFold = node.has_children;
  const hits = cell ? hitsAt(found, node.location_id) : [];
  const contents = contentsText(node, t);
  // The indent the stacked phone layout aligns its lines under the name with.
  const indent = { "--indent": `${node.depth * 20}px` } as CSSProperties;
  const fill = (
    <>
      {cell ? (
        <FillBar cell={cell} />
      ) : summary?.average_fill != null ? (
        <AverageFill average={summary.average_fill} />
      ) : null}
      {cell?.unmeasured && (
        <p className="text-xs text-on-secondary">{t("occupancy.unmeasured")}</p>
      )}
    </>
  );

  return (
    <tr
      {...trProps}
      className={cn(
        "block align-middle md:table-row",
        summary ? "bg-surface-raised/50" : "hover:bg-surface-raised/50",
        hits.length > 0 && "bg-yellow-50 dark:bg-yellow-500/10",
      )}
    >
      <td className="block px-4 pb-0 pt-2 md:table-cell md:py-2">
        <div
          className="flex min-w-0 items-center gap-1"
          style={{ paddingLeft: `${node.depth * 20}px` }}
        >
          {canFold || mixed ? (
            <Button
              variant="ghost"
              size="inline"
              aria-expanded={canFold ? !isFolded : isOpened}
              aria-label={
                (canFold ? !isFolded : isOpened)
                  ? t("occupancy.collapse", { name: node.name })
                  : t("occupancy.expand", { name: node.name })
              }
              onClick={() =>
                canFold
                  ? onToggleFold(node.location_id)
                  : onToggleOpen(node.location_id)
              }
              className="h-7 w-7 shrink-0 text-on-muted hover:text-on"
            >
              <ChevronRight
                size={16}
                className={cn(
                  "transition-transform",
                  (canFold ? !isFolded : isOpened) && "rotate-90",
                )}
              />
            </Button>
          ) : (
            <span className="h-7 w-7 shrink-0" aria-hidden="true" />
          )}
          {cell ? (
            <Button
              variant="ghost"
              size="inline"
              onClick={() => onOpenSettings(node)}
              className="min-w-0 justify-start truncate px-1 py-0.5 text-left text-sm font-medium text-on"
            >
              {node.name}
            </Button>
          ) : (
            <span className="min-w-0 truncate text-sm font-semibold text-on">
              {node.name}
            </span>
          )}
          {node.short_code && (
            <span className="shrink-0 font-mono text-[10px] uppercase text-on-muted">
              {node.short_code}
            </span>
          )}
          {hits.map((hit) => (
            <span
              key={hit.productId}
              className="shrink-0 rounded-full bg-yellow-100 px-2 py-0.5 text-xs text-yellow-900"
            >
              {hitQuantity(hit)}
            </span>
          ))}
        </div>
      </td>
      <td
        className="block px-4 py-1 pl-[calc(3.25rem+var(--indent))] md:table-cell md:py-1 md:pl-4"
        style={indent}
      >
        {fill}
      </td>
      <td
        className="block px-4 pb-2 pl-[calc(3.25rem+var(--indent))] text-xs text-on-secondary md:table-cell md:py-1 md:pl-4"
        style={indent}
      >
        {contents}
      </td>
      <td className="hidden px-4 py-1 text-xs tabular-nums text-on-secondary md:table-cell">
        {node.sequence ?? ""}
      </td>
    </tr>
  );
}

function ProductRow({
  node,
  entry,
  trProps,
}: {
  node: OccupancyNode;
  entry: OccupancyEntry;
  trProps: TrProps;
}) {
  const { t } = useTranslation("warehouse");
  const unit = entry.product_unit_symbol ?? "";
  const tone = statusTone(node.cell?.status ?? "ok");
  const indent = { "--indent": `${node.depth * 20 + 20}px` } as CSSProperties;
  return (
    <tr {...trProps} className="block bg-surface-raised/30 md:table-row">
      <td className="block px-4 pb-0 pt-2 md:table-cell md:py-2">
        <span
          className="block truncate text-sm text-on-secondary"
          style={{ paddingLeft: `${node.depth * 20 + 36}px` }}
        >
          {entry.product_template_name}
        </span>
      </td>
      <td
        className="block px-4 py-0.5 pl-[calc(3.25rem+var(--indent))] text-xs tabular-nums text-on-secondary md:table-cell md:py-1 md:pl-4"
        style={indent}
      >
        {entry.share === null ? (
          t("occupancy.noLimit")
        ) : (
          <span className={cn(tone.text)}>
            {t("occupancy.share", { fill: entry.share })}
          </span>
        )}
      </td>
      <td
        className="block px-4 pb-2 pl-[calc(3.25rem+var(--indent))] text-xs tabular-nums text-on-secondary md:table-cell md:py-1 md:pl-4"
        style={indent}
      >
        {entry.max_quantity === null
          ? `${formatQuantityLocale(entry.quantity)} ${unit}`
          : t("occupancy.quantityOfLimit", {
              quantity: formatQuantityLocale(entry.quantity),
              limit: formatQuantityLocale(entry.max_quantity),
              unit,
            })}
      </td>
      <td className="hidden md:table-cell" />
    </tr>
  );
}

/** Under an opened shelf whose own read failed: an empty list would lie. */
function FailureRow({
  node,
  failure,
  trProps,
}: {
  node: OccupancyNode;
  failure: LookupFailure;
  trProps: TrProps;
}) {
  const { t } = useTranslation("warehouse");
  return (
    <tr {...trProps} className="block bg-surface-raised/30 md:table-row">
      <td
        colSpan={4}
        className="block px-4 py-2 md:table-cell"
        // Under the product names it stands in for.
        style={{ paddingLeft: `${node.depth * 20 + 52}px` }}
      >
        <InlineQueryError
          error={failure.error}
          onRetry={failure.retry}
          message={t("errors.loadShelfFailed")}
        />
      </td>
    </tr>
  );
}
