import { useQuery } from "@tanstack/react-query";
import { storagesApi } from "@/lib/api/storages";
import { queryKeys } from "@/hooks/queries/keys";
import { isIdentifierRejection } from "@/lib/errors";
import { useLocationsById } from "@/module-sdk";
import type {
  StorageLocationBreadcrumb,
  StorageLocationSummary,
} from "@/types";

/**
 * The location the address names: the row the lists would show for it (counts
 * and inherited fields included), the way down to it, and — when the lists
 * keep it off — why.
 *
 * Asked by id, never found in a list: the screen needs this one place, and
 * the levels around it load only when the reader opens them. A miss in the
 * scoped lists has more than one cause — the identifier is unknown, or the
 * location is module-owned, virtual or archived — so a second read, naming
 * the place without the scope, runs only when the first found nothing.
 */
export function useSelectedStorage(
  selectedId: string | undefined,
  excludeModuleContexts: boolean,
) {
  const id = selectedId ?? "";
  const scoped = useQuery({
    queryKey: [
      ...queryKeys.storages.all,
      "selected",
      id,
      { exclude: excludeModuleContexts },
    ],
    queryFn: async (): Promise<StorageLocationSummary | null> => {
      const page = await storagesApi.getPage({
        ids: [id],
        exclude_module_contexts: excludeModuleContexts || undefined,
        limit: 1,
      });
      return page.items[0] ?? null;
    },
    enabled: !!selectedId,
  });
  const malformed = isIdentifierRejection(scoped.error);
  const missed = scoped.data === null;
  const named = useLocationsById(missed ? [id] : []);
  const breadcrumb = useQuery<StorageLocationBreadcrumb[]>({
    // Under the namespace root, so a rename or a move refreshes the path.
    queryKey: [...queryKeys.storages.all, "breadcrumb", id],
    queryFn: () => storagesApi.getBreadcrumb(id),
    enabled: !!selectedId && scoped.data != null,
  });

  const lookupPending = missed && named.isLoading;
  return {
    /** The row, when the lists show this place. */
    summary: scoped.data ?? undefined,
    /** The place the lists keep off, to say why. */
    withheld: missed ? named.byId.get(id) : undefined,
    /** Root first, the place itself last. */
    path: breadcrumb.data ?? [],
    isLoading: !!selectedId && (scoped.isLoading || lookupPending),
    // The way down is part of what the pane draws: without it the place
    // would read as standing at the top.
    isError:
      (scoped.isError && !malformed) ||
      breadcrumb.isError ||
      (missed && named.isError),
    refetch: () => {
      void scoped.refetch();
      void breadcrumb.refetch();
      if (missed) void named.refetch();
    },
  };
}
