import { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { usersApi } from "@/lib/api/admin";
import { queryKeys } from "@/hooks/queries/keys";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { invalidation } from "@/lib/api/invalidation";
import { documentsApi } from "@/modules/warehouse/api/documents";
import type { WorkItem } from "@/modules/warehouse/types";
import { useQueuedSearchParams } from "@/module-sdk";

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
  const [searchParams, writeParams] = useQueuedSearchParams();
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
    writeParams((next) => next.delete("replenish"));
  }, [replenishId, tasks, total, writeParams, onOpen, loadAll]);
}

/**
 * The people a task can be given to, by the grant its action needs — a member
 * who can only read is on the list of members and cannot do any of them, and
 * a count is not offered to someone who writes only the warehouse.
 *
 * The cache entry holds the full member records, the shape every other reader
 * of this key stores (the approvals pickers, the audit-log filters); the
 * `{ id, name }` view is made here, so no reader sees another's shape. Until
 * the holders are known nobody is offered, and a failure of either call is
 * reported as one.
 */
export function useAssignableMembers(enabled: boolean) {
  const members = useQuery({
    queryKey: queryKeys.users.orgMembers,
    queryFn: () => usersApi.getOrgMembers(),
    enabled,
    staleTime: 30_000,
  });
  const holders = useQuery({
    queryKey: [...queryKeys.documents.all, "work-item-assignees"],
    queryFn: documentsApi.workItemAssignees,
    enabled,
    staleTime: 30_000,
  });
  const named = useMemo(() => {
    if (!members.data) return undefined;
    const byId = new Map(
      members.data.map((member) => [
        member.id,
        member.full_name || member.email,
      ]),
    );
    return byId;
  }, [members.data]);
  const byPermission = useMemo(() => {
    if (!named || !holders.data) return undefined;
    return Object.fromEntries(
      Object.entries(holders.data.byPermission).map(([grant, ids]) => [
        grant,
        ids
          .filter((id) => named.has(id))
          .map((id) => ({ id, name: named.get(id) ?? id })),
      ]),
    );
  }, [named, holders.data]);
  const data = useMemo(() => {
    if (!named || !holders.data) return undefined;
    const allowed = new Set(holders.data.userIds);
    return [...named.entries()]
      .filter(([id]) => allowed.has(id))
      .map(([id, name]) => ({ id, name }));
  }, [named, holders.data]);
  return {
    data,
    byPermission,
    isError: members.isError || holders.isError,
  };
}
