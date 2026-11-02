import { useMemo } from "react";
import { useQueries, type UseQueryResult } from "@tanstack/react-query";
import { storagesApi } from "@/lib/api/storages";
import { queryKeys } from "@/hooks/queries/keys";
import { useStoragesTree } from "@/hooks/queries/useStoragesTree";
import type { StorageLocationNode } from "@/types";

/** Put each loaded branch under the node it belongs to. */
function attachBranches(
  nodes: StorageLocationNode[],
  branches: ReadonlyMap<string, StorageLocationNode[]>,
): StorageLocationNode[] {
  return nodes.map((node) => {
    const below = branches.get(node.id);
    return below
      ? { ...node, children: attachBranches(below, branches) }
      : node;
  });
}

function combineBranches(
  results: ReadonlyArray<UseQueryResult<StorageLocationNode[]>>,
) {
  const loaded = new Map<string, StorageLocationNode[]>();
  results.forEach(({ data }) => {
    const parentId = data?.[0]?.parent_id;
    if (data && parentId) loaded.set(parentId, data);
  });
  const failed = results.filter((result) => result.isError);
  return {
    loaded,
    error: failed[0]?.error ?? null,
    retry: () => failed.forEach((result) => void result.refetch()),
  };
}

/**
 * The location tree as far as the reader has opened it.
 *
 * The roots come first (one level, with the record counts printed on them);
 * a branch is read only when its row is opened, one level at a time, so the
 * screen holds the places it shows and the number of requests follows the
 * number of folds the reader opened rather than the size of the warehouse.
 * A node carries `children_count`, which is how a row knows it has a branch
 * before the branch has arrived.
 *
 * `expanded` may name ids the roots do not show yet (the ancestors of a deep
 * link): their levels load top-down as each one arrives.
 *
 * A level that could not be read is reported (`error`, `retry`), so a row
 * that opened onto nothing is never mistaken for an empty place.
 */
export function useStorageBranches(
  expanded: ReadonlySet<string>,
  options: { excludeModuleContexts: boolean },
) {
  const roots = useStoragesTree(undefined, {
    excludeModuleContexts: options.excludeModuleContexts,
    depth: 1,
  });

  // Which opened rows are known to have nothing under them: asking for a
  // leaf's branch is a request for an empty list.
  const knownLeaves = useMemo(() => {
    const leaves = new Set<string>();
    const visit = (nodes: StorageLocationNode[]) =>
      nodes.forEach((node) => {
        if (node.children_count === 0) leaves.add(node.id);
        visit(node.children);
      });
    visit(roots.data ?? []);
    return leaves;
  }, [roots.data]);

  const openIds = useMemo(() => [...expanded].sort(), [expanded]);
  const branches = useQueries({
    queries: openIds.map((id) => ({
      queryKey: [
        ...queryKeys.storages.tree,
        ...(options.excludeModuleContexts ? ["exclude-module-contexts"] : []),
        "parent",
        id,
        "depth",
        1,
      ],
      queryFn: () =>
        storagesApi.getTree(undefined, {
          excludeModuleContexts: options.excludeModuleContexts,
          parentId: id,
          depth: 1,
        }),
      enabled: !knownLeaves.has(id),
    })),
    // A level knows its own parent, so the map needs no list of ids; an
    // empty level has nothing to attach.
    combine: combineBranches,
  });

  const nodes = useMemo(
    () => attachBranches(roots.data ?? [], branches.loaded),
    [roots.data, branches.loaded],
  );

  return {
    nodes,
    error: roots.error ?? branches.error,
    retry: () => {
      if (roots.isError) void roots.refetch();
      branches.retry();
    },
  };
}
