import { useQuery } from "@tanstack/react-query";
import { storagesApi } from "@/lib/api/storages";
import { queryKeys } from "@/hooks/queries/keys";
import type { StorageLocationNode } from "@/types";

interface TreeOptions {
  excludeModuleContexts?: boolean;
  /** The levels below this place instead of from the roots. */
  parentId?: string;
  /** How many levels to read; the last carries `children_count` and no
   *  children. Without it the whole tree comes back. */
  depth?: number;
  /** False skips the record counts (they read zero): the aggregate behind
   *  them runs over everything below the places answered. */
  counts?: boolean;
  enabled?: boolean;
}

/** The organization's locations as a tree — a Core question, since every
 *  module that moves goods has to say where they stand. A screen that draws
 *  the whole tree asks for it whole; any other asks for the level it shows
 *  (`depth`), and opens a branch with `parentId` when the reader does. */
export function useStoragesTree(usage?: string, options?: TreeOptions) {
  return useQuery<StorageLocationNode[]>({
    // The exclusion and the usage scope are part of the cache identity: a
    // filtered tree and a full one are different results for the same
    // endpoint.
    queryKey: [
      ...queryKeys.storages.tree,
      ...(options?.excludeModuleContexts ? ["exclude-module-contexts"] : []),
      ...(usage ? ["usage", usage] : []),
      ...(options?.parentId ? ["parent", options.parentId] : []),
      ...(options?.depth ? ["depth", options.depth] : []),
      ...(options?.counts === false ? ["no-counts"] : []),
    ],
    queryFn: () => storagesApi.getTree(usage, options),
    enabled: options?.enabled ?? true,
  });
}
