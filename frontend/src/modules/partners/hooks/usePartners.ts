import { useQueries } from "@tanstack/react-query";
import { useModules } from "@/contexts/ModulesContext";
import { useAppMutation } from "@/lib/api/mutationFactory";
import {
  partnersApi,
  type PartnersListParams,
} from "@/modules/partners/api/partners";
import type { Partner, PartnerCreate, PartnerUpdate } from "@/types";
import { queryKeys } from "@/hooks/queries/keys";
import { invalidation } from "@/lib/api/invalidation";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";

export function usePartners(params?: PartnersListParams) {
  return useModuleQuery("partners", {
    queryKey: [...queryKeys.partners.all, params],
    queryFn: () => partnersApi.list(params),
  });
}

/**
 * One partner by id.
 *
 * Screens that need a single partner used to search for it in `usePartners()`,
 * which lists the active ones up to a page size — so a deactivated supplier, or
 * the 101st, simply was not there and the screen showed a raw UUID or lost the
 * e-mail address.
 */
export function usePartner(
  id: string | null | undefined,
  initialData?: Partner,
) {
  return useModuleQuery("partners", {
    queryKey: queryKeys.partners.detail(id ?? ""),
    queryFn: () => partnersApi.getById(id as string),
    initialData,
    extraEnabled: !!id,
  });
}

/**
 * The names of the partners a screen points at, read by id.
 *
 * A screen that names a few partners (the supplier of each price, the
 * preferred supplier of each rule) used to look them up in a list capped at a
 * page, so the one past the cap printed as a raw id. Each is read on its own
 * and shares the cache of `usePartner`; a partner that cannot be read is left
 * out and the caller falls back to whatever it shows without a name.
 */
export function usePartnerNames(
  ids: readonly (string | null | undefined)[],
): Map<string, string> {
  const { isModuleEnabled } = useModules();
  const enabled = isModuleEnabled("partners");
  const wanted = [...new Set(ids.filter((id): id is string => !!id))];
  return useQueries({
    queries: wanted.map((id) => ({
      queryKey: queryKeys.partners.detail(id),
      queryFn: () => partnersApi.getById(id),
      enabled,
    })),
    combine: (results) =>
      new Map(
        results.flatMap((result, i) =>
          result.data ? [[wanted[i], result.data.name] as const] : [],
        ),
      ),
  });
}

export function useCreatePartner() {
  return useAppMutation(
    (data: PartnerCreate) => partnersApi.create(data),
    (qc) => {
      invalidation.partners(qc);
    },
  );
}

export function useUpdatePartner() {
  return useAppMutation(
    ({ id, data }: { id: string; data: PartnerUpdate }) =>
      partnersApi.update(id, data),
    (qc) => {
      invalidation.partners(qc);
    },
  );
}

export function useDeactivatePartner() {
  return useAppMutation(
    (id: string) => partnersApi.deactivate(id),
    (qc) => {
      invalidation.partners(qc);
    },
  );
}

export function useActivatePartner() {
  return useAppMutation(
    (id: string) => partnersApi.activate(id),
    (qc) => {
      invalidation.partners(qc);
    },
  );
}

export function useImportPartners() {
  return useAppMutation(
    ({
      file,
      mapping,
      defaultType,
    }: {
      file: File;
      mapping: unknown;
      defaultType: string;
    }) => partnersApi.importPartners(file, mapping, defaultType),
    (qc) => {
      invalidation.partners(qc);
    },
  );
}
