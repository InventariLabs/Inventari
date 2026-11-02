import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { storagesApi } from "@/lib/api/storages";
import { queryKeys } from "@/hooks/queries/keys";

/** Rows of the Contents table on one page. */
export const CHILDREN_PAGE_SIZE = 50;

/**
 * What stands directly inside a location, one page at a time, with the counts
 * the Contents table prints. The page is read for the location that is open;
 * the siblings of its parent, and every other branch, stay on the server.
 */
export function useStorageChildren(
  parentId: string,
  options: { excludeModuleContexts: boolean; skip: number },
) {
  return useQuery({
    queryKey: [
      ...queryKeys.storages.all,
      "children",
      parentId,
      { exclude: options.excludeModuleContexts, skip: options.skip },
    ],
    queryFn: () =>
      storagesApi.getPage({
        parent_id: parentId,
        exclude_module_contexts: options.excludeModuleContexts || undefined,
        limit: CHILDREN_PAGE_SIZE,
        offset: options.skip,
      }),
    placeholderData: keepPreviousData,
  });
}
