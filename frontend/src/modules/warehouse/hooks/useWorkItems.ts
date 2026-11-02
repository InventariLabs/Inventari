import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { usersApi } from "@/lib/api/admin";
import { queryKeys } from "@/hooks/queries/keys";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { invalidation } from "@/lib/api/invalidation";
import { documentsApi } from "@/modules/warehouse/api/documents";
import type { WorkItem } from "@/modules/warehouse/types";

/** Give a task to a person, or to nobody. With `onlyIfUnassigned` the task
 * is claimed only while nobody holds it, and a task somebody took first is
 * refused instead of being taken from them. */
export function useAssignWorkItem() {
  return useAppMutation(
    (vars: {
      sourceKind: string;
      sourceId: string;
      assigneeId: string | null;
      onlyIfUnassigned?: boolean;
    }) =>
      documentsApi.assignWorkItem(
        vars.sourceKind,
        vars.sourceId,
        vars.assigneeId,
        { onlyIfUnassigned: vars.onlyIfUnassigned },
      ),
    (qc) => {
      invalidation.documents(qc);
    },
  );
}

/** Begin the count a due schedule asks for. */
export function useStartCount() {
  return useAppMutation(documentsApi.startCount, (qc) => {
    invalidation.documents(qc);
  });
}

/** Add a task of your own to the list. */
export function useCreateCustomWorkItem() {
  return useAppMutation(documentsApi.createCustomWorkItem, (qc) => {
    invalidation.documents(qc);
  });
}

/** Tick a custom task off. */
export function useSetCustomWorkItemDone() {
  return useAppMutation(
    (vars: { id: string; done: boolean }) =>
      documentsApi.setCustomWorkItemDone(vars.id, vars.done),
    (qc) => {
      invalidation.documents(qc);
    },
  );
}

/** Remove a custom task. */
export function useDeleteCustomWorkItem() {
  return useAppMutation(documentsApi.deleteCustomWorkItem, (qc) => {
    invalidation.documents(qc);
  });
}

/** This week's measures for the strip above the work board. */
export function useWorkMeasures(refetchInterval?: number) {
  return useModuleQuery("warehouse", {
    queryKey: [...queryKeys.documents.all, "work-measures"],
    queryFn: documentsApi.workMeasures,
    refetchInterval,
  });
}

/** Put away goods waiting in a receiving area. */
export function usePutAwayWorkItem() {
  return useAppMutation(documentsApi.putAwayWorkItem, (qc) => {
    invalidation.documents(qc);
    invalidation.storages(qc);
  });
}

/** The reserve move a replenishment alert proposes, with its lines prepared. */
export function useReplenishmentProposal(ruleId: string) {
  return useModuleQuery("warehouse", {
    queryKey: queryKeys.documents.replenishmentProposal(ruleId),
    queryFn: () => documentsApi.getReplenishmentProposal(ruleId),
  });
}

/** Post the proposed reserve move — the one-step transfer it prepared. */
export function usePostReplenishmentProposal() {
  return useAppMutation(documentsApi.postReplenishmentProposal, (qc) => {
    invalidation.documents(qc);
    invalidation.storages(qc);
    // The alert that raised the task is gone with the shortage; the
    // replenishment screen reads its own cache and would keep offering it.
    qc.invalidateQueries({
      queryKey: queryKeys.purchaseOrders.replenishmentAlerts(),
    });
  });
}

/** Opens the task an address names: the work board's card links back here
 * with the replenishment rule, and the sheet opens over the same queue. The
 * parameter is dropped once the sheet is up, so closing it leaves an ordinary
 * To do page. The queue lists a page of tasks at a time, so a task that lies
 * past the loaded ones is looked for by asking for the rest of the list
 * (`loadAll`) rather than waiting for a "Show more" nobody pressed. */
export function useOpenReplenishmentLink(
  tasks: WorkItem[],
  total: number,
  onOpen: (item: WorkItem) => void,
  loadAll: () => void,
) {
  const [searchParams, setSearchParams] = useSearchParams();
  const replenishId = searchParams.get("replenish");
  useEffect(() => {
    if (!replenishId) return;
    const task = tasks.find(
      (row) =>
        row.source_kind === "replenishment" && row.source_id === replenishId,
    );
    if (!task) {
      if (tasks.length < total) loadAll();
      return;
    }
    onOpen(task);
    const next = new URLSearchParams(searchParams);
    next.delete("replenish");
    setSearchParams(next, { replace: true });
  }, [
    replenishId,
    tasks,
    total,
    searchParams,
    setSearchParams,
    onOpen,
    loadAll,
  ]);
}

/**
 * The people a task can be given to: the organization's active members.
 *
 * The cache entry holds the full member records, the shape every other reader
 * of this key stores (the approvals pickers, the audit-log filters); the
 * `{ id, name }` view is made in `select`, so no reader sees another's shape.
 */
export function useAssignableMembers(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.users.orgMembers,
    queryFn: () => usersApi.getOrgMembers(),
    select: (members) =>
      members.map((member) => ({
        id: member.id,
        name: member.full_name || member.email,
      })),
    enabled,
    staleTime: 30_000,
  });
}
