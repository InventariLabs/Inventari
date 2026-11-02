import { useQuery } from "@tanstack/react-query";
import { storagesApi } from "@/lib/api/storages";
import { queryKeys } from "@/hooks/queries/keys";

/**
 * How many locations the module-data policy is keeping off this list.
 *
 * The twin of `useHiddenCategoryCount`, and the third list of that
 * navigation section to get one. Here the probe was gated on the filtered
 * tree being *empty*, so the fact only ever reached a reader who had no
 * locations at all — and an organization that came from a starter pack
 * always has some. With rows on screen the list simply did not ask how
 * many it was hiding, so it had nothing to say.
 *
 * The count is the unfiltered answer minus what the filtered list shows, the
 * way the category twin does it: the backend decides which context tags a
 * switched-off module claims, so counting tagged rows here over-counts every
 * tag that stays on the list.
 *
 * The probe steps aside while the reader is narrowing the list themselves:
 * a stale unfiltered answer must not speak over their own filtering, and a
 * narrowed list must not pay for a request it will not use.
 */
export function useHiddenStorageCount(
  excludeModuleContexts: boolean,
  isLoading: boolean,
  filtersActive: boolean,
): number {
  const shouldProbe = excludeModuleContexts && !isLoading && !filtersActive;
  // Two counts, no rows: the totals of a one-row page. Neither the list the
  // screen shows nor the unfiltered one is read to learn how far apart they
  // are.
  const shown = useQuery({
    queryKey: [...queryKeys.storages.all, "total", "scoped"],
    queryFn: () =>
      storagesApi.getPage({
        exclude_module_contexts: true,
        counts: false,
        limit: 1,
      }),
    enabled: shouldProbe,
  });
  const every = useQuery({
    queryKey: [...queryKeys.storages.all, "total", "every"],
    queryFn: () => storagesApi.getPage({ counts: false, limit: 1 }),
    enabled: shouldProbe,
  });
  // A probe that failed has no count to give; the list beside it reports its
  // own failure, so this stays quiet instead of claiming nothing is hidden.
  if (!shouldProbe || !shown.data || !every.data) return 0;
  return Math.max(every.data.total - shown.data.total, 0);
}
