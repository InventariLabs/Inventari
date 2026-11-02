import { useState } from "react";
import { useTranslation } from "react-i18next";
import { CornerLeftUp } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import {
  Sheet,
  SheetBody,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/Sheet";
import {
  LocationSearchFailed,
  useLocationSearch,
  useLocationsById,
} from "@/module-sdk";
import { useDebounce } from "@/module-sdk";
import { useStorageBranches } from "@/modules/spaces/hooks/useStorageBranches";
import { isVirtualUsage } from "@/modules/shared/lib/storageUsage";
import { storagesApi } from "@/lib/api/storages";
import type { StorageLocationNode, StorageLocationSummary } from "@/types";
import { isInsidePath } from "./LocationTargetPicker";
import { StorageScanField } from "./StorageScanField";
import { StorageTree } from "./StorageTree";

interface StorageMovePickerProps {
  open: boolean;
  /** The locations being moved — their subtrees are not destinations. */
  movingIds: string[];
  /** Whether the organization keeps module-owned places out of the lists. */
  excludeModuleContexts: boolean;
  onClose: () => void;
  onPick: (parentId: string | null) => void;
}

/** Drop the moved places from the levels the picker has open. */
function pruneTree(
  nodes: StorageLocationNode[],
  excluded: ReadonlySet<string>,
): StorageLocationNode[] {
  return nodes
    .filter((node) => !excluded.has(node.id) && !isVirtualUsage(node.usage))
    .map((node) => ({
      ...node,
      children: pruneTree(node.children ?? [], excluded),
    }));
}

/**
 * "Move to…": the destination of one location, or of the rows selected in
 * Contents, chosen from a searchable tree or by scanning its label.
 *
 * The location itself and everything inside it are absent rather than shown
 * disabled: a destination that can never be picked is a promise the picker
 * would break, and the server refuses the move anyway. The tree opens one
 * level at a time, so what stands inside a moved place is never loaded: it
 * is recognised by its path, which a search result and a scanned label carry.
 */
export function StorageMovePicker({
  open,
  movingIds,
  excludeModuleContexts,
  onClose,
  onPick,
}: StorageMovePickerProps) {
  const { t } = useTranslation(["locations", "common"]);
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const tree = useStorageBranches(expanded, { excludeModuleContexts });
  const { nodes } = tree;
  const moving = useLocationsById(movingIds);
  const movingPaths = movingIds
    .map((id) => moving.byId.get(id)?.full_path)
    .filter((path): path is string => !!path);

  const excluded = new Set(movingIds);
  const targets = pruneTree(nodes, excluded);

  const isDestination = (row: StorageLocationSummary) =>
    !excluded.has(row.id) &&
    !isVirtualUsage(row.usage) &&
    !movingPaths.some((path) => isInsidePath(row.full_path, path));

  const typed = search.trim();
  const debounced = useDebounce(typed, 300);
  const found = useLocationSearch({ purpose: "general" }, debounced, {
    limit: 30,
    enabled: debounced.length > 0,
  });
  // The moved places' own paths are what keeps their subtrees out of the
  // answer, so a failed read of either is a failed search, not a shorter list.
  const searchFailed = found.isError || moving.isError;
  const matches = searchFailed
    ? []
    : (found.data?.items ?? []).filter(isDestination);

  // A label scanned on the floor names the destination as surely as a tap
  // does — on a phone there is no tree to drag through — but a label of the
  // location being moved, or of one inside it, names no destination at all.
  const handleScanned = (id: string, code: string) => {
    void storagesApi
      .getPage({
        ids: [id],
        usage: "all",
        include_archived: true,
        counts: false,
      })
      .then((page) => {
        const row = page.items[0];
        if (!row || !isDestination(row)) {
          toast.error(t("locations:move.scanNotTarget", { code }));
          return;
        }
        onPick(id);
      });
    return false;
  };

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const title =
    movingIds.length === 1
      ? t("locations:move.titleOne")
      : t("locations:move.titleMany", { count: movingIds.length });

  return (
    <Sheet
      open={open}
      onClose={onClose}
      maxWidth="lg"
      zIndex="modal-nested"
      aria-label={title}
    >
      <SheetHeader>
        <SheetTitle>{title}</SheetTitle>
      </SheetHeader>
      <SheetBody className="space-y-3">
        <Input
          placeholder={t("locations:move.searchPlaceholder")}
          aria-label={t("locations:move.searchPlaceholder")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <Button
          variant="ghost"
          className="w-full justify-start"
          leftIcon={<CornerLeftUp size={16} />}
          onClick={() => onPick(null)}
        >
          {t("locations:reorg.moveToTop")}
        </Button>
        <StorageScanField onSelect={handleScanned} />
        {typed ? (
          <ul
            aria-label={t("locations:move.targetsLabel")}
            className="space-y-0.5"
          >
            {matches.map((row) => (
              <li key={row.id}>
                <Button
                  variant="ghost"
                  size="row"
                  onClick={() => onPick(row.id)}
                  className="justify-start"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm text-on">
                      {row.name}
                    </span>
                    <span className="block truncate text-xs text-on-muted">
                      {row.full_path}
                    </span>
                  </span>
                </Button>
              </li>
            ))}
            {searchFailed && (
              <li className="px-2 py-3 text-sm text-on-muted">
                <LocationSearchFailed
                  onRetry={() => {
                    void found.refetch();
                    void moving.refetch();
                  }}
                />
              </li>
            )}
            {!searchFailed &&
              matches.length === 0 &&
              !found.isLoading &&
              typed === debounced && (
                <li className="px-2 py-3 text-sm text-on-muted">
                  {t("locations:tree.noMatches")}
                </li>
              )}
          </ul>
        ) : (
          <>
            <StorageTree
              nodes={targets}
              expanded={expanded}
              onToggle={toggle}
              onSelect={(id) => onPick(id)}
              canWrite={false}
              onMoveTo={() => undefined}
              onDragMove={() => undefined}
              label={t("locations:move.targetsLabel")}
            />
            {tree.error ? (
              <p className="py-4 text-center text-sm text-on-muted">
                <LocationSearchFailed onRetry={tree.retry} />
              </p>
            ) : (
              targets.length === 0 && (
                <p className="py-4 text-center text-sm text-on-muted">
                  {t("locations:reorg.noMoveTargets")}
                </p>
              )
            )}
          </>
        )}
      </SheetBody>
      <SheetFooter>
        <Button variant="outline" onClick={onClose}>
          {t("common:actions.cancel")}
        </Button>
      </SheetFooter>
    </Sheet>
  );
}
