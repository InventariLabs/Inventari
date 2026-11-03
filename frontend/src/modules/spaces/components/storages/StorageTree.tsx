import { useMemo, useRef, useState } from "react";
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
          selectedId={selectedId}
          expanded={expanded}
          tabStop={tabStop}
          canWrite={canWrite}
          draggingId={draggingId}
          dragOverId={dragOverId}
          onToggle={onToggle}
          onSelect={(id) => {
            setFocusedId(id);
            onSelect(id);
          }}
          onMoveTo={onMoveTo}
          onOpenSettings={onOpenSettings}
          onKeyDown={handleKeyDown}
          onDragStart={setDraggingId}
          onDragEnd={() => {
            setDraggingId(null);
            setDragOverId(null);
          }}
          onDragOver={setDragOverId}
          onDragLeave={(id) =>
            setDragOverId((current) => (current === id ? null : current))
          }
          onDrop={(target) => {
            if (canDropOn(target) && draggingId) {
              onDragMove(draggingId, target.id);
            }
            setDraggingId(null);
            setDragOverId(null);
          }}
          canDropOn={canDropOn}
        />
      )}
    </div>
  );
}

interface TreeLevelProps {
  nodes: StorageLocationNode[];
  level: number;
  selectedId?: string;
  expanded: Set<string>;
  tabStop?: string;
  canWrite: boolean;
  draggingId: string | null;
  dragOverId: string | null;
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

function TreeLevel(props: TreeLevelProps) {
  return (
    <>
      {props.nodes.map((node) => (
        <TreeRow key={node.id} node={node} {...props} />
      ))}
    </>
  );
}

function TreeRow({
  node,
  level,
  selectedId,
  expanded,
  tabStop,
  canWrite,
  draggingId,
  dragOverId,
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
}: TreeLevelProps & { node: StorageLocationNode }) {
  const { t } = useTranslation("locations");
  const children = node.children ?? [];
  const hasChildren = hasBranch(node);
  const isExpanded = expanded.has(node.id);
  const selectable = !isVirtualUsage(node.usage);

  return (
    <>
      <div
        role="treeitem"
        aria-level={level}
        aria-selected={selectedId === node.id}
        {...(hasChildren ? { "aria-expanded": isExpanded } : {})}
        data-tree-node={node.id}
        tabIndex={tabStop === node.id ? 0 : -1}
        onClick={() => onSelect(node.id)}
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
          selectedId === node.id
            ? "bg-primary-50 text-primary-800 dark:bg-primary-950/40 dark:text-primary-200"
            : "text-on",
          dragOverId === node.id && "ring-2 ring-primary-400",
          draggingId === node.id && "opacity-50",
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
          title={t("counts.inSublocations", {
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
            selectedId={selectedId}
            expanded={expanded}
            tabStop={tabStop}
            canWrite={canWrite}
            draggingId={draggingId}
            dragOverId={dragOverId}
            onToggle={onToggle}
            onSelect={onSelect}
            onMoveTo={onMoveTo}
            onOpenSettings={onOpenSettings}
            onKeyDown={onKeyDown}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
            canDropOn={canDropOn}
          />
        </div>
      )}
    </>
  );
}
