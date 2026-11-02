import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { cn } from "@/lib/utils";
import { formatQuantityLocale } from "@/utils/formatters";
import type { LookupFailure } from "@/modules/warehouse/hooks/useOccupancyLookups";
import {
  hitQuantity,
  hitsAt,
  onlyProduct,
  pathOf,
  statusTone,
  type HitsByLocation,
  type OccupancyCell,
  type OccupancyEntry,
  type OccupancyHit,
  type OccupancyNode,
} from "./occupancyModel";

/** A block with more shelves than this switches to small tiles. */
const DENSE_FROM = 40;

interface Block {
  key: string;
  container: OccupancyNode | null;
  shelves: OccupancyNode[];
}

/** Shelves grouped under the location that holds them, in walk order. */
function toBlocks(nodes: OccupancyNode[], byId: Map<string, OccupancyNode>) {
  const blocks = new Map<string, Block>();
  for (const node of nodes) {
    if (!node.cell) continue;
    const key = node.parent_id ?? "top";
    let block = blocks.get(key);
    if (!block) {
      block = {
        key,
        container: node.parent_id ? (byId.get(node.parent_id) ?? null) : null,
        shelves: [],
      };
      blocks.set(key, block);
    }
    block.shelves.push(node);
  }
  return [...blocks.values()];
}

function tileClass(cell: OccupancyCell): string {
  switch (cell.status) {
    case "over":
      return "border-red-500 bg-red-100 text-on-danger dark:bg-red-500/20";
    case "nearly_full":
      return "border-amber-500 bg-amber-100 text-on-warning dark:bg-amber-500/20";
    case "ok": {
      const fill = cell.fill ?? 0;
      return cn(
        "border-blue-600 text-on",
        fill >= 60
          ? "bg-blue-200 dark:bg-blue-500/30"
          : fill >= 30
            ? "bg-blue-100 dark:bg-blue-500/20"
            : "bg-blue-50 dark:bg-blue-500/10",
      );
    }
    case "no_limit":
      return "border-dashed border-gray-400 bg-surface-card text-on-secondary";
    default:
      return "border-border bg-surface-raised text-on-secondary";
  }
}

interface OccupancyMapProps {
  /** The nodes that pass the filter, in walk order. */
  nodes: OccupancyNode[];
  /** Every node, for the paths. */
  byId: Map<string, OccupancyNode>;
  hits: HitsByLocation;
  pickedId: string | null;
  /** Every product of the picked shelf, once its own read has answered. */
  pickedEntries: OccupancyEntry[] | undefined;
  /** The picked shelf's own read failed. */
  pickedFailure: LookupFailure | undefined;
  onPick: (id: string | null) => void;
  onOpenSettings: (node: OccupancyNode) => void;
}

/** The heat map: each zone a block, each shelf a tile in walk order. */
export function OccupancyMap({
  nodes,
  byId,
  hits,
  pickedId,
  pickedEntries,
  pickedFailure,
  onPick,
  onOpenSettings,
}: OccupancyMapProps) {
  const { t } = useTranslation("warehouse");
  const blocks = toBlocks(nodes, byId);
  const picked = pickedId ? byId.get(pickedId) : undefined;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {blocks.map((block) => {
          const dense = block.shelves.length > DENSE_FROM;
          const title = block.container?.name ?? t("occupancy.map.topLevel");
          return (
            <section
              key={block.key}
              aria-label={title}
              className={cn(
                "space-y-2 rounded-xl border border-border bg-surface-card p-3",
                // A zone of hundreds of shelves takes the width it needs: in
                // one third of the row it was eight tiles wide and taller
                // than a screen.
                dense && "sm:col-span-2 xl:col-span-3",
              )}
            >
              <div>
                {block.container?.parent_id && (
                  <p className="text-xs text-on-secondary">
                    {pathOf(byId, byId.get(block.container.parent_id)!)}
                  </p>
                )}
                <h3 className="text-sm font-semibold text-on">{title}</h3>
                <p className="text-xs text-on-secondary">
                  {t("occupancy.summary.locations", {
                    count: block.shelves.length,
                  })}
                  {" · "}
                  {t("occupancy.summary.withLimit", {
                    count: block.shelves.filter((n) => n.cell?.fill != null)
                      .length,
                  })}
                </p>
              </div>
              <div
                className={cn(
                  "grid gap-1.5",
                  dense
                    ? "grid-cols-[repeat(auto-fill,minmax(2.75rem,1fr))]"
                    : "grid-cols-2 sm:grid-cols-3",
                )}
              >
                {block.shelves.map((node) => (
                  <Tile
                    key={node.location_id}
                    node={node}
                    cell={node.cell!}
                    dense={dense}
                    hits={hitsAt(hits, node.location_id)}
                    picked={pickedId === node.location_id}
                    onPick={onPick}
                  />
                ))}
              </div>
            </section>
          );
        })}
      </div>
      {picked?.cell && (
        <PickedShelf
          node={picked}
          entries={pickedEntries}
          failure={pickedFailure}
          path={pathOf(byId, picked)}
          onClose={() => onPick(null)}
          onOpenSettings={onOpenSettings}
        />
      )}
    </div>
  );
}

type Translate = ReturnType<typeof useTranslation>["t"];

/** An empty shelf says so, whether or not it has a limit. */
function isEmptyShelf(cell: OccupancyCell): boolean {
  return cell.status === "empty";
}

function tileLabel(cell: OccupancyCell, hits: OccupancyHit[], t: Translate) {
  const state = isEmptyShelf(cell)
    ? t("occupancy.empty")
    : cell.fill !== null
      ? t("occupancy.percentFull", { fill: cell.fill })
      : t("occupancy.noLimit");
  const found = hits.map(hitQuantity).join(", ");
  return `${cell.location_name ?? ""}: ${state}${found ? ` · ${found}` : ""}`;
}

/** What a tile prints besides the name: the percentage, or its stand-in. */
function tileFigure(cell: OccupancyCell, dense: boolean, t: Translate) {
  if (isEmptyShelf(cell)) return t("occupancy.emptyShort");
  if (cell.fill !== null) return t("occupancy.percent", { fill: cell.fill });
  return dense ? "∞" : t("occupancy.noLimitShort");
}

/**
 * The second line of a tile: what the search found there, else, for a shelf
 * without a limit, what lies on it — its quantity is all that shelf has to say.
 */
function tileQuantity(cell: OccupancyCell, hits: OccupancyHit[], t: Translate) {
  if (hits.length > 0) return hits.map(hitQuantity).join(", ");
  if (cell.status !== "no_limit") return null;
  const only = onlyProduct(cell);
  if (only)
    return hitQuantity({
      quantity: only.quantity,
      unit: only.product_unit_symbol ?? null,
    });
  return t("occupancy.products", { count: cell.products });
}

function Tile({
  node,
  cell,
  dense,
  hits,
  picked,
  onPick,
}: {
  node: OccupancyNode;
  cell: OccupancyCell;
  dense: boolean;
  hits: OccupancyHit[];
  picked: boolean;
  onPick: (id: string | null) => void;
}) {
  const { t } = useTranslation("warehouse");
  const label = tileLabel(cell, hits, t);
  const figure = tileFigure(cell, dense, t);
  const quantity = tileQuantity(cell, hits, t);
  return (
    <Button
      variant="ghost"
      size="inline"
      aria-label={label}
      aria-pressed={picked}
      title={dense ? label : undefined}
      onClick={() => onPick(picked ? null : node.location_id)}
      className={cn(
        "group relative border text-xs",
        tileClass(cell),
        dense
          ? "min-h-7 min-w-11 flex-col rounded px-0.5 text-[10px] leading-tight tabular-nums"
          : "min-h-16 flex-col items-stretch justify-between rounded-lg p-2 text-left",
        // The style is spelled as a property: tailwind-merge reads a bare
        // `outline` as the width and drops it beside `outline-[3px]`, which
        // left the ring with a width and no style, so it never drew.
        hits.length > 0 &&
          "outline-[3px] outline-offset-1 outline-yellow-400 [outline-style:solid]",
        picked && "ring-2 ring-primary-500",
      )}
    >
      {dense ? (
        <>
          <span aria-hidden="true" className="max-w-full truncate">
            {figure}
          </span>
          {quantity && (
            <span
              aria-hidden="true"
              className="max-w-full truncate text-on-secondary"
            >
              {quantity}
            </span>
          )}
        </>
      ) : (
        <>
          <span className="line-clamp-2 text-xs leading-tight">
            {node.name}
          </span>
          <span className="text-sm font-medium tabular-nums">{figure}</span>
          {quantity && (
            <span className="text-xs tabular-nums text-on-secondary">
              {quantity}
            </span>
          )}
        </>
      )}
    </Button>
  );
}

function PickedShelf({
  node,
  entries: listed,
  failure,
  path,
  onClose,
  onOpenSettings,
}: {
  node: OccupancyNode;
  entries: OccupancyEntry[] | undefined;
  failure: LookupFailure | undefined;
  path: string;
  onClose: () => void;
  onOpenSettings: (node: OccupancyNode) => void;
}) {
  const { t } = useTranslation("warehouse");
  const cell = node.cell!;
  // Until the shelf's own read answers, the overview's part of the list —
  // its limited products — is what there is to show.
  const entries = listed ?? cell.entries;
  const tone = statusTone(cell.status);
  const ref = useRef<HTMLElement>(null);
  // The panel sits under the whole grid, so a tile picked high in a large
  // zone changed nothing the reader could see. Bring the panel into view
  // without moving focus off the tile.
  useEffect(() => {
    ref.current?.scrollIntoView?.({ block: "nearest" });
  }, [node.location_id]);
  return (
    <aside
      ref={ref}
      aria-live="polite"
      className="max-w-lg space-y-2 rounded-xl border border-primary-300 bg-surface-card p-4"
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-on">{node.name}</h3>
          <p className="text-xs text-on-secondary">{path}</p>
        </div>
        <Button
          variant="ghost"
          size="iconSm"
          aria-label={t("occupancy.map.close")}
          onClick={onClose}
        >
          <X size={16} />
        </Button>
      </div>
      {failure && (
        <InlineQueryError
          error={failure.error}
          onRetry={failure.retry}
          message={t("errors.loadShelfFailed")}
        />
      )}
      {cell.products === 0 && entries.length === 0 ? (
        <p className="text-sm text-on-secondary">
          {t("occupancy.map.nothing")}
        </p>
      ) : (
        <ul className="space-y-1">
          {entries.map((entry) => (
            <li
              key={entry.product_template_id}
              className="flex justify-between gap-3 text-sm"
            >
              <span>{entry.product_template_name}</span>
              <span className="tabular-nums text-on-secondary">
                {entry.max_quantity === null
                  ? `${formatQuantityLocale(entry.quantity)} ${entry.product_unit_symbol ?? ""}`
                  : `${t("occupancy.quantityOfLimit", {
                      quantity: formatQuantityLocale(entry.quantity),
                      limit: formatQuantityLocale(entry.max_quantity),
                      unit: entry.product_unit_symbol ?? "",
                    })} · ${t("occupancy.percent", { fill: entry.share ?? 0 })}`}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className={cn("text-sm font-medium", tone.text)}>
        {cell.fill === null
          ? cell.status === "empty"
            ? t("occupancy.map.emptyShelf")
            : t("occupancy.map.noLimitHint")
          : cell.status === "over"
            ? t("occupancy.map.totalOver", { fill: cell.fill })
            : t("occupancy.map.total", { fill: cell.fill })}
      </p>
      <Button
        variant="link"
        size="contentSm"
        className="min-h-11 px-0 py-2 md:min-h-10"
        onClick={() => onOpenSettings(node)}
      >
        {t("occupancy.map.setLimits")}
      </Button>
    </aside>
  );
}
