import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronRight, GripVertical, Move } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/ui/Card";
import { extractApiError } from "@/lib/errors";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { useBomTree, useMoveBomLine } from "@/modules/maker/hooks/useBom";
import { YieldLossNote } from "@/modules/maker/components/YieldLossNote";
import type { BomTreeNode } from "@/modules/maker/types/maker";

interface BomTreeEditorProps {
  templateId: string;
  /** The recipe at the root — a variant's own formula. Without it, the
   *  template's default recipe. */
  recipeId?: string;
}

function shortId(id: string | null | undefined): string {
  if (!id) return "—";
  return id.slice(0, 8);
}

interface NodeRowProps {
  node: BomTreeNode;
  depth: number;
  onDragStart: (lineId: string) => void;
  onDropOnNode: (targetLineId: string) => void;
  collapsed: Record<string, boolean>;
  toggleCollapse: (lineId: string) => void;
}

function NodeRow({
  node,
  depth,
  onDragStart,
  onDropOnNode,
  collapsed,
  toggleCollapse,
}: NodeRowProps) {
  const { t } = useTranslation("maker");
  const hasChildren = node.children.length > 0;

  if (!node.line) return null;
  const { line } = node;

  const isCollapsed = collapsed[line.id] ?? false;
  const dropTargetNewParent =
    hasChildren && !isCollapsed ? line.child_template_id : null;

  return (
    <div className="space-y-1">
      <div
        className="flex items-center gap-2 p-2 rounded-md hover:bg-surface-raised border border-transparent hover:border-border transition-colors text-sm"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        draggable
        onDragStart={(e) => {
          e.dataTransfer.setData("text/plain", line.id);
          e.dataTransfer.effectAllowed = "move";
          onDragStart(line.id);
        }}
        onDragOver={(e) => {
          if (dropTargetNewParent === null) return;
          e.preventDefault();
          e.dataTransfer.dropEffect = "move";
        }}
        onDrop={(e) => {
          if (dropTargetNewParent === null) return;
          e.preventDefault();
          onDropOnNode(line.id);
        }}
        data-testid={`maker-tree-node-${line.id}`}
      >
        <GripVertical
          size={14}
          className="text-on-muted cursor-grab active:cursor-grabbing"
        />
        {hasChildren ? (
          // Inline icon-only toggle inside a row; full <Button> chrome is
          // too heavy for this micro-interaction and shifts indentation.
          // eslint-disable-next-line no-restricted-syntax
          <button
            type="button"
            onClick={() => toggleCollapse(line.id)}
            className="p-0.5 text-on-muted hover:text-on"
            aria-label={isCollapsed ? "Expand" : "Collapse"}
          >
            {isCollapsed ? (
              <ChevronRight size={14} />
            ) : (
              <ChevronDown size={14} />
            )}
          </button>
        ) : (
          <span className="w-4" />
        )}
        <span className="font-medium text-sm text-on truncate">
          {line.child_template_name ?? shortId(line.child_template_id)}
        </span>
        <span className="text-on-secondary">
          {formatQuantityLocalized(t, line.qty_per_batch, line.unit)}
        </span>
        <YieldLossNote pct={line.yield_loss_pct} />
        <Move
          size={12}
          className="ml-auto text-on-muted opacity-40"
          aria-label={t("tree.dropHint")}
        />
      </div>
      {!isCollapsed &&
        node.children.map((child) => (
          <NodeRow
            key={child.line?.id ?? Math.random().toString()}
            node={child}
            depth={depth + 1}
            onDragStart={onDragStart}
            onDropOnNode={onDropOnNode}
            collapsed={collapsed}
            toggleCollapse={toggleCollapse}
          />
        ))}
    </div>
  );
}

/**
 * Recursive BoM tree editor. Drag a line and drop it onto another line
 * to make it a child of that line's child template (sent as
 * ``new_parent_template_id``). Cycles are detected by the backend.
 */
export function BomTreeEditor({ templateId, recipeId }: BomTreeEditorProps) {
  const { t } = useTranslation("maker");
  const [draggedLineId, setDraggedLineId] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const { data, isLoading, error } = useBomTree(templateId, recipeId);
  const moveMutation = useMoveBomLine(templateId);

  function handleDragStart(lineId: string) {
    setDraggedLineId(lineId);
  }

  function handleDropOnNode(targetLineId: string) {
    if (!data || draggedLineId === null) return;
    if (draggedLineId === targetLineId) {
      setDraggedLineId(null);
      return;
    }
    const targetNode = findNode(data.root.children, targetLineId);
    if (!targetNode?.line) {
      setDraggedLineId(null);
      return;
    }
    const newParentId = targetNode.line.child_template_id;
    moveMutation.mutate(
      { lineId: draggedLineId, data: { new_parent_template_id: newParentId } },
      {
        onSuccess: () => {
          toast.success(t("tree.moved"));
        },
        onError: (err) => {
          toast.error(extractApiError(err, t("tree.moveError")));
        },
      },
    );
    setDraggedLineId(null);
  }

  function toggleCollapse(lineId: string) {
    setCollapsed((prev) => ({ ...prev, [lineId]: !(prev[lineId] ?? false) }));
  }

  if (isLoading) {
    return (
      <Card className="p-6 text-center text-on-muted text-sm">
        {t("tree.loading")}
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="p-4 bg-red-50 border-red-100 text-red-700 text-sm">
        {extractApiError(error, t("tree.error"))}
      </Card>
    );
  }

  const totalLines = countLines(data?.root ?? null);

  return (
    <Card className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs uppercase tracking-widest text-on-muted font-medium px-1">
          {t("tree.title")} ({totalLines})
        </h3>
        {/* Nothing to drag onto nothing: with fewer than two rows the hint
            describes a gesture that cannot be made, which reads as an
            instruction the reader is failing to follow. */}
        {totalLines > 1 && (
          <span className="text-xs text-on-muted" data-testid="maker-tree-hint">
            {t("tree.hint")}
          </span>
        )}
      </div>
      {totalLines === 0 ? (
        <div className="text-sm text-on-muted p-6 text-center">
          {t("tree.empty")}
        </div>
      ) : (
        <div className="space-y-1">
          {(data?.root.children ?? []).map((child) => (
            <NodeRow
              key={child.line?.id ?? Math.random().toString()}
              node={child}
              depth={0}
              onDragStart={handleDragStart}
              onDropOnNode={handleDropOnNode}
              collapsed={collapsed}
              toggleCollapse={toggleCollapse}
            />
          ))}
        </div>
      )}
    </Card>
  );
}

function findNode(children: BomTreeNode[], lineId: string): BomTreeNode | null {
  for (const child of children) {
    if (child.line?.id === lineId) return child;
    const found = findNode(child.children, lineId);
    if (found) return found;
  }
  return null;
}

function countLines(node: BomTreeNode | null): number {
  if (!node) return 0;
  return node.children.reduce(
    (acc, c) => acc + (c.line ? 1 : 0) + countLines(c),
    0,
  );
}
