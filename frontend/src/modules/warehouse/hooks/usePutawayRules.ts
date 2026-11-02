import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import { queryKeys } from "@/hooks/queries/keys";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { invalidation } from "@/lib/api/invalidation";
import {
  homeShelfApi,
  putawayApi,
  receivingModesApi,
  type WarehouseReceiving,
  type PutawayRule,
  type PutawayRuleCreate,
  type PutawayRuleUpdate,
} from "@/modules/warehouse/api/putaway";

/** List all putaway rules for the current organization. */
export function usePutawayRules() {
  return useModuleQuery<PutawayRule[]>("warehouse", {
    queryKey: queryKeys.documents.putawayRules,
    queryFn: () => putawayApi.list(),
  });
}

/** Create a new putaway rule. */
export function useCreatePutawayRule() {
  return useAppMutation(
    (data: PutawayRuleCreate) => putawayApi.create(data),
    (qc) => {
      invalidation.putawayRules(qc);
    },
  );
}

/** Update an existing putaway rule. */
export function useUpdatePutawayRule() {
  return useAppMutation(
    ({ id, data }: { id: string; data: PutawayRuleUpdate }) =>
      putawayApi.update(id, data),
    (qc) => {
      invalidation.putawayRules(qc);
    },
  );
}

/** Delete a putaway rule. */
export function useDeletePutawayRule() {
  return useAppMutation(
    (id: string) => putawayApi.delete(id),
    (qc) => {
      invalidation.putawayRules(qc);
    },
  );
}

/** How each warehouse that chose receives. */
export function useReceivingModes() {
  return useModuleQuery<WarehouseReceiving[]>("warehouse", {
    queryKey: queryKeys.documents.putawayReceivingModes,
    queryFn: () => receivingModesApi.list(),
  });
}

/** Choose one step or two for a warehouse; two make its receiving area. */
export function useSetReceivingMode() {
  return useAppMutation(receivingModesApi.set, (qc) => {
    qc.invalidateQueries({
      queryKey: queryKeys.documents.putawayReceivingModes,
    });
    invalidation.storages(qc);
  });
}

/** Make a location the product's home: the rules list shows it like any rule. */
export function useMakeHomeShelf() {
  return useAppMutation(homeShelfApi.set, (qc) => {
    invalidation.putawayRules(qc);
    invalidation.documents(qc);
  });
}

/** The products whose put-away does not ask for a home location. */
export function useSilencedHomeShelves() {
  return useModuleQuery("warehouse", {
    queryKey: queryKeys.documents.putawayHomeSilenced,
    queryFn: () => homeShelfApi.listSilenced(),
  });
}

/** Stop asking about a product's home location. */
export function useSilenceHomeShelf() {
  return useAppMutation(homeShelfApi.silence, (qc) => {
    qc.invalidateQueries({ queryKey: queryKeys.documents.putawayHomeSilenced });
  });
}

/** Ask about a product's home location again. */
export function useUnsilenceHomeShelf() {
  return useAppMutation(homeShelfApi.unsilence, (qc) => {
    qc.invalidateQueries({ queryKey: queryKeys.documents.putawayHomeSilenced });
  });
}
