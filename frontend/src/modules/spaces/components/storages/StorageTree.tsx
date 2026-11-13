import { memo, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Box, Boxes, ChevronRight } from "lucide-react";
import { ActionMenu } from "@/components/ui/ActionMenu";
import { Button } from "@/components/ui/Button";
import { TypedSlot } from "@/components/Slot";
import { cn } from "@/lib/utils";
import { isVirtualUsage } from "@/modules/shared/lib/storageUsage";
import { descendantIdsOf } from "@/modules/spaces/lib/storageTree";
import type { StorageLocationNode } from "@/types";

/** A row with a branch: its children are here, or the server says it has some. */
function hasBranch(node: StorageLocationNode | undefined): boolean {
  return (
    !!node && (node.children_count > 0 || (node.children ?? []).length > 0)
  );
}

interface StorageTreeProps {
  nodes: StorageLocationNode[];
  selectedId?: string;
  expanded: Set<string>;
  onToggle: (id: string) => void;
  onSelect: (id: string) => void;
  canWrite: boolean;
  /** Opens the "Move to…" picker for one location. */
  onMoveTo: (id: string) => void;
  /** Opens the Settings tab of one location, where Archive and Delete live. */
  onOpenSettings: (id: string) => void;
  /** Desktop shortcut: drop *id* onto *parentId*. */
  onDragMove: (id: string, parentId: string) => void;
  label: string;
}

/**
 * The location tree beside the selected location.
 *
 * A real tree for the keyboard and the screen reader (`role="tree"` /
 * `treeitem` / `group`, roving tabindex, arrow keys), not a nested list that
 * only looks like one: the owner's screen had three levels of cards with no
 * single place to see the shape of the warehouse.
 *
 * Dragging is the desktop shortcut for what "Move to…" does with a tap; HTML5
 * drag events never fire on a touchscreen, so the menu is the only path there.
 */
export function StorageTree({
  nodes,
  selectedId,
  expanded,
  onToggle,
  onSelect,
  canWrite,
  onMoveTo,
  onOpenSettings,
  onDragMove,
  label,
}: StorageTreeProps) {
  const { t } = useTranslation("locations");
  const treeRef = useRef<HTMLDivElement>(null);
  const [focusedId, setFocusedId] = useState<string | undefined>(selectedId);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dragOverId, setDragOverId] = useState<string | null>(null);

  const visibleNodes = useMemo(() => {
    const shown = (list: StorageLocationNode[]): StorageLocationNode[] =>
      list.flatMap((node) => [
        node,
        ...(expanded.has(node.id) ? shown(node.children ?? []) : []),
      ]);
    return shown(nodes);
  }, [nodes, expanded]);

  // The roving tab stop follows the last row the reader touched; when that
  // row folds away the first one takes the tab, so Tab always lands inside
  // the tree instead of skipping it.
  const tabStop =
    focusedId && visibleNodes.some((node) => node.id === focusedId)
      ? focusedId
      : visibleNodes[0]?.id;

  const focusRow = (id: string | undefined) => {
    if (!id) return;
    setFocusedId(id);
    treeRef.current
      ?.querySelector<HTMLElement>(`[data-tree-node="${id}"]`)
      ?.focus();
  };

  const moveHorizontal = (
    direction: 1 | -1,
    rows: HTMLElement[],
    index: number,
    id: string,
    level: number,
  ) => {
    if (direction === 1) {
      const node = visibleNodes.find((entry) => entry.id === id);
      if (hasBranch(node) && !expanded.has(id)) {
        onToggle(id);
        return;
      }
      const next = rows[index + 1];
      if (next && Number(next.getAttribute("aria-level")) === level + 1) {
        focusRow(next.dataset.treeNode);
      }
      return;
    }
    // Only a row that is an open branch folds; a leaf can sit in `expanded`
    // (selecting or searching adds it) without being one.
    if (rows[index]?.getAttribute("aria-expanded") === "true") {
      onToggle(id);
      return;
    }
    // The parent is the nearest row above one level up; the row right above
    // is a sibling, or the last row of a sibling's open subtree, for every
    // child but the first.
    const parent = rows
      .slice(0, index)
      .reverse()
      .find((row) => Number(row.getAttribute("aria-level")) === level - 1);
    focusRow(parent?.dataset.treeNode);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const row = (event.target as HTMLElement).closest<HTMLElement>(
      '[role="treeitem"]',
    );
    if (!row) return;
    // A menu inside a row owns its own keys.
    if ((event.target as HTMLElement).closest("[data-tree-menu]")) return;
    const rows = Array.from(
      treeRef.current?.querySelectorAll<HTMLElement>('[role="treeitem"]') ?? [],
    );
    const index = rows.indexOf(row);
    const id = row.dataset.treeNode ?? "";
    const level = Number(row.getAttribute("aria-level") ?? "1");

    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      focusRow(
        rows[index + (event.key === "ArrowDown" ? 1 : -1)]?.dataset.treeNode,
      );
      return;
    }
    if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      focusRow(
        rows[event.key === "Home" ? 0 : rows.length - 1]?.dataset.treeNode,
      );
      return;
    }
    if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      event.preventDefault();
      moveHorizontal(
        event.key === "ArrowRight" ? 1 : -1,
        rows,
        index,
        id,
        level,
      );
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect(id);
    }
  };

  const excludedTargets = useMemo(
    () => (draggingId ? descendantIdsOf(nodes, draggingId) : new Set<string>()),
    [nodes, draggingId],
  );
  const canDropOn = (target: StorageLocationNode) =>
    draggingId !== null &&
    draggingId !== target.id &&
    !isVirtualUsage(target.usage) &&
    !excludedTargets.has(target.id);

  // The rows are memoized, so what they are handed has to keep its identity
  // across renders: these forward to the latest closures, which change with
  // every selection, drag and keystroke. Without them one click redraws every
  // row of a level with thousands of places.
  const latest = useRef({
    onToggle,
    onSelect,
    onMoveTo,
    onOpenSettings,
    onDragMove,
    handleKeyDown,
    canDropOn,
    draggingId,
  });
  latest.current = {
    onToggle,
    onSelect,
    onMoveTo,
    onOpenSettings,
    onDragMove,
    handleKeyDown,
    canDropOn,
    draggingId,
  };
  const handlers = useMemo<TreeHandlers>(
    () => ({
      onToggle: (id) => latest.current.onToggle(id),
      onSelect: (id) => {
        setFocusedId(id);
        latest.current.onSelect(id);
      },
      onMoveTo: (id) => latest.current.onMoveTo(id),
      onOpenSettings: (id) => latest.current.onOpenSettings(id),
      onKeyDown: (event) => latest.current.handleKeyDown(event),
      onDragStart: setDraggingId,
      onDragEnd: () => {
        setDraggingId(null);
        setDragOverId(null);
      },
      onDragOver: setDragOverId,
      onDragLeave: (id) =>
        setDragOverId((current) => (current === id ? null : current)),
      onDrop: (target) => {
        const {
          canDropOn: canDrop,
          draggingId: dragged,
          onDragMove: move,
        } = latest.current;
        if (canDrop(target) && dragged) move(dragged, target.id);
        setDraggingId(null);
        setDragOverId(null);
      },
      canDropOn: (target) => latest.current.canDropOn(target),
    }),
    [],
  );

  return (
    <div
      ref={treeRef}
      role="tree"
      aria-label={label}
      className="flex flex-col gap-0.5"
    >
      {visibleNodes.length === 0 ? (
        <p className="px-2 py-3 text-sm text-on-muted">{t("tree.empty")}</p>
      ) : (
        <TreeLevel
          nodes={nodes}
          level={1}
          canWrite={canWrite}
          handlers={handlers}
          view={{ selectedId, expanded, tabStop, draggingId, dragOverId }}
        />
      )}
    </div>
  );
}

/** What the rows ask of the tree. Identity-stable, so a row can be memoized. */
interface TreeHandlers {
  onToggle: (id: string) => void;
  onSelect: (id: string) => void;
  onMoveTo: (id: string) => void;
  onOpenSettings: (id: string) => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLDivElement>) => void;
  onDragStart: (id: string) => void;
  onDragEnd: () => void;
  onDragOver: (id: string) => void;
  onDragLeave: (id: string) => void;
  onDrop: (node: StorageLocationNode) => void;
  canDropOn: (node: StorageLocationNode) => boolean;
}

/** The state that changes with a click or a drag; each row reads its own slice. */
interface TreeView {
  selectedId?: string;
  expanded: Set<string>;
  tabStop?: string;
  draggingId: string | null;
  dragOverId: string | null;
}

interface TreeLevelProps {
  nodes: StorageLocationNode[];
  level: number;
  canWrite: boolean;
  handlers: TreeHandlers;
  view: TreeView;
}

function TreeLevel({ nodes, level, canWrite, handlers, view }: TreeLevelProps) {
  return (
    <>
      {nodes.map((node) => (
        <TreeRow
          key={node.id}
          node={node}
          level={level}
          canWrite={canWrite}
          handlers={handlers}
          view={view}
          selected={view.selectedId === node.id}
          isExpanded={view.expanded.has(node.id)}
          tabbable={view.tabStop === node.id}
          dragging={view.draggingId === node.id}
          dragOver={view.dragOverId === node.id}
        />
      ))}
    </>
  );
}

interface TreeRowProps extends Omit<TreeLevelProps, "nodes"> {
  node: StorageLocationNode;
  selected: boolean;
  isExpanded: boolean;
  tabbable: boolean;
  dragging: boolean;
  dragOver: boolean;
}

/**
 * A row repaints only when its own look changed. `view` is the whole tree's
 * state, which only an open branch passes on to its children, so a closed
 * row ignores it: choosing a row among thousands touches two of them.
 */
function sameRow(prev: TreeRowProps, next: TreeRowProps): boolean {
  return (
    prev.node === next.node &&
    prev.level === next.level &&
    prev.canWrite === next.canWrite &&
    prev.handlers === next.handlers &&
    prev.selected === next.selected &&
    prev.isExpanded === next.isExpanded &&
    prev.tabbable === next.tabbable &&
    prev.dragging === next.dragging &&
    prev.dragOver === next.dragOver &&
    (!next.isExpanded || prev.view === next.view)
  );
}

const TreeRow = memo(function TreeRow({
  node,
  level,
  canWrite,
  handlers,
  view,
  selected,
  isExpanded,
  tabbable,
  dragging,
  dragOver,
}: TreeRowProps) {
  const {
    onToggle,
    onSelect,
    onMoveTo,
    onOpenSettings,
    onKeyDown,
    onDragStart,
    onDragEnd,
    onDragOver,
    onDragLeave,
    onDrop,
    canDropOn,
  } = handlers;
  const { t } = useTranslation("locations");
  const children = node.children ?? [];
  const hasChildren = hasBranch(node);
  const selectable = !isVirtualUsage(node.usage);

  return (
    <>
      <div
        role="treeitem"
        aria-level={level}
        aria-selected={selected}
        {...(hasChildren ? { "aria-expanded": isExpanded } : {})}
        data-tree-node={node.id}
        tabIndex={tabbable ? 0 : -1}
        onClick={(event) => {
          // The row's menu renders in a portal, outside this element in the
          // DOM, yet React still bubbles its clicks here. A menu item that
          // navigates (Archive or delete…) would be overwritten by this
          // re-select of the row.
          if (!event.currentTarget.contains(event.target as Node)) return;
          onSelect(node.id);
        }}
        onKeyDown={onKeyDown}
        draggable={canWrite && selectable}
        onDragStart={(event) => {
          if (!canWrite || !selectable) return;
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("text/plain", node.id);
          onDragStart(node.id);
        }}
        onDragEnd={onDragEnd}
        onDragOver={(event) => {
          if (!canDropOn(node)) return;
          event.preventDefault();
          event.dataTransfer.dropEffect = "move";
          onDragOver(node.id);
        }}
        onDragLeave={() => onDragLeave(node.id)}
        onDrop={(event) => {
          if (!canDropOn(node)) return;
          event.preventDefault();
          onDrop(node);
        }}
        className={cn(
          "group flex cursor-pointer items-center gap-1 rounded-lg pr-1 text-sm",
          "hover:bg-surface-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          selected
            ? "bg-primary-50 text-primary-800 dark:bg-primary-950/40 dark:text-primary-200"
            : "text-on",
          dragOver && "ring-2 ring-primary-400",
          dragging && "opacity-50",
        )}
        style={{ paddingLeft: `${(level - 1) * 14 + 4}px` }}
      >
        {hasChildren ? (
          <Button
            variant="ghost"
            size="inline"
            tabIndex={-1}
            aria-label={
              isExpanded
                ? t("tree.collapse", { name: node.name })
                : t("tree.expand", { name: node.name })
            }
            onClick={(event) => {
              event.stopPropagation();
              onToggle(node.id);
            }}
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded p-0 text-on-muted hover:text-on"
          >
            <ChevronRight
              size={16}
              className={cn("transition-transform", isExpanded && "rotate-90")}
            />
          </Button>
        ) : (
          <span className="h-6 w-6 shrink-0" aria-hidden="true" />
        )}
        {hasChildren ? (
          <Boxes
            size={15}
            className="shrink-0 text-on-muted"
            aria-hidden="true"
          />
        ) : (
          <Box
            size={15}
            className="shrink-0 text-on-muted"
            aria-hidden="true"
          />
        )}
        <span className="min-w-0 flex-1 truncate">{node.name}</span>
        {node.short_code && (
          <span className="shrink-0 font-mono text-[10px] uppercase tracking-tight text-on-muted">
            {node.short_code}
          </span>
        )}
        <TypedSlot
          name="storage_tree_row_extra"
          data={{ storageId: node.id }}
          className="shrink-0"
        />
        <span
          className="shrink-0 rounded-md bg-surface-inset px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-on-secondary"
          title={t("counts.recordsInside", {
            count: node.subtree_items_count,
          })}
        >
          {node.subtree_items_count}
        </span>
        {canWrite && selectable && (
          <span data-tree-menu>
            <ActionMenu
              label={t("tree.rowActions", { name: node.name })}
              actions={[
                {
                  id: "move",
                  label: t("reorg.moveTo"),
                  onSelect: () => onMoveTo(node.id),
                },
                {
                  id: "settings",
                  label: t("reorg.archiveOrDelete"),
                  onSelect: () => onOpenSettings(node.id),
                },
              ]}
              triggerClassName="h-6 w-6"
            />
          </span>
        )}
      </div>
      {hasChildren && isExpanded && (
        <div role="group">
          <TreeLevel
            nodes={children}
            level={level + 1}
            canWrite={canWrite}
            handlers={handlers}
            view={view}
          />
        </div>
      )}
    </>
  );
}, sameRow);
