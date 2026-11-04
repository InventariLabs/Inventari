import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Archive, Search } from "lucide-react";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { LocationSearchFailed, useLocationSearch } from "@/module-sdk";
import { useDebounce } from "@/module-sdk";
import { useStorageBranches } from "@/modules/spaces/hooks/useStorageBranches";
import { findNode } from "@/modules/spaces/lib/storageTree";
import { StorageScanField } from "./StorageScanField";
import { StorageTree } from "./StorageTree";
import type { StorageLocationSummary } from "@/types";

interface StorageTreePanelProps {
  /** Whether the organization keeps module-owned places out of the lists. */
  excludeModuleContexts: boolean;
  selectedId?: string;
  /** The places above the selected one, root first: opened so it shows. */
  openPath?: readonly string[];
  onSelect: (id: string) => void;
  canWrite: boolean;
  onMoveTo: (id: string) => void;
  onOpenSettings: (id: string) => void;
  onDragMove: (id: string, parentId: string) => void;
}

/**
 * Everything beside the tree that names one of its rows: the search over
 * names and codes, and the field a location label is scanned into.
 *
 * Scanning is what the floor does instead of walking a tree; typing a short
 * code into the same field does the same thing, so a label whose print is
 * still in the printer is not a dead end.
 *
 * The tree holds the levels the reader opened. A search is asked of the
 * server and answers with the places themselves and the way to each, because
 * a tree filtered in the browser would need the whole tree first.
 */
export function StorageTreePanel({
  excludeModuleContexts,
  selectedId,
  openPath = [],
  onSelect,
  canWrite,
  onMoveTo,
  onOpenSettings,
  onDragMove,
}: StorageTreePanelProps) {
  const { t } = useTranslation(["locations", "common"]);
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const tree = useStorageBranches(expanded, { excludeModuleContexts });
  const { nodes } = tree;
  const typed = search.trim();
  const debounced = useDebounce(typed, 300);
  const found = useLocationSearch({ purpose: "general" }, debounced, {
    limit: 30,
    enabled: debounced.length > 0,
  });

  // The selected location may sit under a closed branch — arrive by deep
  // link, by scan, or by clicking a row of the Contents table and it opens
  // the branches above it, and its own, so what stands inside is visible
  // without a second click.
  const selectedHasBranch =
    (findNode(nodes, selectedId)?.children_count ?? 0) > 0;
  const pathKey = openPath.join(",");
  useEffect(() => {
    const chain = [
      ...(pathKey ? pathKey.split(",") : []),
      ...(selectedId && selectedHasBranch ? [selectedId] : []),
    ];
    if (chain.length === 0) return;
    setExpanded((prev) => {
      const next = new Set(prev);
      chain.forEach((id) => next.add(id));
      return next.size === prev.size ? prev : next;
    });
  }, [pathKey, selectedId, selectedHasBranch]);

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="space-y-3">
      <Input
        leftIcon={<Search size={16} />}
        aria-label={t("locations:tree.searchPlaceholder")}
        placeholder={t("locations:tree.searchPlaceholder")}
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />
      <StorageScanField onSelect={onSelect} />
      {/* Above the scrolled tree, not under it: the branch that failed may be
          anywhere in a long tree, and the word has to be where the eye is. */}
      {!typed && tree.error && (
        <p className="px-2 text-sm text-on-muted">
          <LocationSearchFailed onRetry={tree.retry} />
        </p>
      )}
      <div className="max-h-[calc(100vh-22rem)] overflow-y-auto pr-1">
        {typed && found.isError ? (
          <p className="px-2 py-3 text-sm text-on-muted">
            <LocationSearchFailed onRetry={() => void found.refetch()} />
          </p>
        ) : typed ? (
          <SearchResults
            rows={found.data?.items}
            waiting={found.isLoading || typed !== debounced}
            selectedId={selectedId}
            onSelect={onSelect}
          />
        ) : (
          <StorageTree
            nodes={nodes}
            selectedId={selectedId}
            expanded={expanded}
            onToggle={toggle}
            onSelect={onSelect}
            canWrite={canWrite}
            onMoveTo={onMoveTo}
            onOpenSettings={onOpenSettings}
            onDragMove={onDragMove}
            label={t("locations:tree.label")}
          />
        )}
      </div>
      <Link
        to="/inventory/locations/archived"
        className="inline-flex items-center gap-1.5 px-1 text-sm text-on-muted hover:text-on"
      >
        <Archive size={14} aria-hidden="true" />
        {t("locations:tree.archivedLink")}
      </Link>
    </div>
  );
}

function SearchResults({
  rows,
  waiting,
  selectedId,
  onSelect,
}: {
  rows: StorageLocationSummary[] | undefined;
  waiting: boolean;
  selectedId?: string;
  onSelect: (id: string) => void;
}) {
  const { t } = useTranslation(["locations", "common"]);
  if (!rows) return null;
  if (rows.length === 0 && !waiting) {
    return (
      <p className="px-2 py-3 text-sm text-on-muted">{t("tree.noMatches")}</p>
    );
  }
  return (
    <ul aria-label={t("locations:tree.label")} className="space-y-0.5">
      {rows.map((row) => (
        <li key={row.id}>
          <Button
            variant="ghost"
            size="row"
            aria-current={selectedId === row.id ? "true" : undefined}
            onClick={() => onSelect(row.id)}
            className="justify-between"
          >
            <span className="min-w-0">
              <span className="block truncate text-sm text-on">{row.name}</span>
              <span className="block truncate text-xs text-on-muted">
                {row.full_path}
              </span>
            </span>
            {row.short_code && (
              <span className="shrink-0 font-mono text-[10px] uppercase tracking-tight text-on-muted">
                {row.short_code}
              </span>
            )}
          </Button>
        </li>
      ))}
    </ul>
  );
}
