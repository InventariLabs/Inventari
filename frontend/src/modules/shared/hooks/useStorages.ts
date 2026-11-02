import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { storagesApi } from "@/lib/api/storages";
import type {
  StorageLocation,
  StorageLocationSummary,
  StorageType,
  Item,
} from "@/types";
import { queryKeys } from "@/hooks/queries/keys";

export function useStorages(
  contextTag?: string,
  options?: {
    excludeModuleContexts?: boolean;
    enabled?: boolean;
    /**
     * Usage filter passed to the backend verbatim. The endpoint defaults to
     * internal locations only; 'all' reaches the virtual counterparts
     * (consumed, inventory loss, production) — what the management screen
     * needs and a picker must not offer.
     */
    usage?: string;
    /**
     * Archived rows travel with the answer when set. The default hides
     * them; a listing that names what records stand in needs the ask, a
     * picker never does.
     */
    includeArchived?: boolean;
    /**
     * Locations one vertical module may call its own — tagged for it, or
     * holding its records. What a module's own locations screen wants:
     * `contextTag` alone loses the untagged locations its assets stand in,
     * and no filter at all offers Delete on the whole organization.
     */
    moduleScope?: string;
  },
) {
  const scope = options?.moduleScope;
  const usage = options?.usage;
  const includeArchived = options?.includeArchived;
  return useQuery<StorageLocationSummary[]>({
    queryKey: [
      ...(scope
        ? [...queryKeys.storages.all, "module", scope]
        : contextTag
          ? [...queryKeys.storages.all, "context", contextTag]
          : options?.excludeModuleContexts
            ? [...queryKeys.storages.all, "exclude-module-contexts"]
            : queryKeys.storages.all),
      // A full-usage list and the internal-only default are different answers
      // to the same endpoint — they must not share a cache entry.
      ...(usage ? ["usage", usage] : []),
      ...(includeArchived ? ["archived"] : []),
    ],
    queryFn: () => {
      const params: NonNullable<Parameters<typeof storagesApi.getAll>[0]> = {};
      if (scope) params.module_scope = scope;
      else if (contextTag) params.context_tag = contextTag;
      else if (options?.excludeModuleContexts)
        params.exclude_module_contexts = true;
      if (usage) params.usage = usage;
      if (includeArchived) params.include_archived = true;
      return storagesApi.getAll(
        Object.keys(params).length > 0 ? params : undefined,
      );
    },
    enabled: options?.enabled ?? true,
  });
}

// Lifted to Core so a module may ask where things stand without reaching
// into the spaces module; kept here as the name every caller already uses.
import { useStoragesTree } from "@/module-sdk";

export { useStoragesTree };

export function useStorageTypes() {
  return useQuery<StorageType[]>({
    queryKey: queryKeys.storages.types,
    queryFn: () => storagesApi.getStorageTypes(),
  });
}

/**
 * Whether this organization keeps anything somewhere that watches expiry.
 *
 * The dashboard used to spend half its tiles on "expiring soon" and "expired"
 * for every workspace, including the neutral one, where an expiry date may
 * never be entered. Storage types carry the behaviour, so the question is
 * whether any of the organization's own locations uses one that watches it —
 * which answers "no" for a fresh workspace and turns to "yes" the moment a
 * fridge, a freezer or anything else with a shelf life is added.
 */
/**
 * Half of "does this organization track expiry": whether any location it keeps
 * things in behaves that way. The other half — whether the records themselves
 * carry dates — is answered by the overview, and `useTracksExpiry` beside this
 * file puts the two together. Asking only this one told a warehouse it does
 * not track expiry while eight of its products were past their date.
 */
export function useStorageTypesTrackExpiry(): boolean {
  const { data: types, isError: typesFailed } = useStorageTypes();
  const expiryTypeIds = (types ?? [])
    .filter(
      (type) =>
        type.behavior_mode === "EXPIRY" || type.behavior_mode === "FREEZING",
    )
    .map((type) => type.id);
  // One question of the server — is there any location of those kinds — asked
  // as the total of a one-row page, and only when some kind watches expiry.
  const { data: used, isError: usedFailed } = useQuery({
    queryKey: [...queryKeys.storages.all, "of-types", expiryTypeIds],
    queryFn: () =>
      storagesApi.getPage({
        type_ids: expiryTypeIds,
        counts: false,
        limit: 1,
      }),
    enabled: expiryTypeIds.length > 0,
  });

  // Neither answer can say "nothing here" when it did not arrive. A flag that
  // hides the expiry views must not turn false on a failed request: keep them.
  if (typesFailed || usedFailed) return true;
  return (used?.total ?? 0) > 0;
}

export function useStorage(id: string) {
  return useQuery<StorageLocation>({
    queryKey: queryKeys.storages.detail(id),
    queryFn: () => storagesApi.getById(id),
    enabled: !!id,
  });
}

/** The products standing in a place; `includeInside` adds those of every
 *  place below it, still one request. */
export function useStorageItems(storageId: string, includeInside = false) {
  return useQuery<Item[]>({
    // Under the place's own key, so a change to its products refreshes both.
    queryKey: includeInside
      ? [...queryKeys.storages.items(storageId), "inside"]
      : queryKeys.storages.items(storageId),
    queryFn: () => storagesApi.getItems(storageId, { includeInside }),
    enabled: !!storageId,
    // Ticking the box keeps the list on screen until the wider one arrives.
    placeholderData: keepPreviousData,
  });
}
