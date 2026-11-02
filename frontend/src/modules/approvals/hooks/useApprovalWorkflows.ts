import { useQuery } from "@tanstack/react-query";

import { useAppMutation } from "@/lib/api/mutationFactory";
import { invalidation } from "@/lib/api/invalidation";
import { useEnabledModulesOptional } from "@/contexts/ModulesContext";

import {
  approvalsApi,
  type WorkflowCreateInput,
  type WorkflowUpdateInput,
} from "@/modules/approvals/api/approvals";
import { queryKeys } from "@/hooks/queries/keys";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";

const workflowKeys = {
  all: queryKeys.approvals.workflows,
};

export function useApprovalWorkflows() {
  return useModuleQuery("approvals", {
    queryKey: workflowKeys.all,
    queryFn: () => approvalsApi.listWorkflows(),
    // Every row carries what the workflow holds, worked out from other
    // modules' settings — a change there never invalidates this key. Held for
    // the app-wide five minutes, a card kept saying "Holds: documents of type
    // Goods Issue" after the settings had been cleared; so it is re-read
    // whenever the page is shown or the window comes back.
    staleTime: 0,
    refetchOnWindowFocus: true,
  });
}

/**
 * Whether a request for this target type would land — the server's answer,
 * not the workflow list's.
 *
 * The list is filtered by ``approvals:read``, so for the accounts that
 * compose requests without any grant over approvals it answers an empty
 * list: not "no workflow", but "not yours to see". The dedicated endpoint
 * answers the one bit without that grant, and its ``true`` is exactly what
 * ``request_approval`` accepts — an active workflow with a stage.
 *
 * ``undefined`` still means the question cannot be answered yet (in
 * flight, an error, the module off). Callers treat only ``false`` as "the
 * engine would refuse a request" and leave every other answer to the API,
 * which is where the last word lives.
 */
export function useIsWorkflowConfigured(
  targetType: string,
): boolean | undefined {
  const approvalsEnabled = useEnabledModulesOptional().includes("approvals");
  const { data, isSuccess } = useQuery({
    queryKey: queryKeys.approvals.workflowConfigured(targetType),
    queryFn: () => approvalsApi.getWorkflowConfigured(targetType),
    enabled: approvalsEnabled,
  });
  if (!isSuccess) return undefined;
  return data.configured;
}

export function useCreateWorkflow() {
  return useAppMutation(
    (data: WorkflowCreateInput) => approvalsApi.createWorkflow(data),
    (qc) => {
      qc.invalidateQueries({ queryKey: workflowKeys.all });
    },
  );
}

export function useUpdateWorkflow() {
  return useAppMutation(
    ({ id, data }: { id: string; data: WorkflowUpdateInput }) =>
      approvalsApi.updateWorkflow(id, data),
    (qc) => {
      qc.invalidateQueries({ queryKey: workflowKeys.all });
      // Switching a workflow off releases its open requests, which clears
      // their notices on the server — refresh the bell.
      invalidation.notifications(qc);
    },
  );
}

export function useDeleteWorkflow() {
  return useAppMutation(
    (id: string) => approvalsApi.deleteWorkflow(id),
    (qc) => {
      qc.invalidateQueries({ queryKey: workflowKeys.all });
      // Switching a workflow off releases its open requests, which clears
      // their notices on the server — refresh the bell.
      invalidation.notifications(qc);
    },
  );
}

/**
 * What switching this workflow off would release — counted by the server when
 * the dialog opens, so the question the admin answers names real numbers.
 */
export function useWorkflowWaiting(id: string | null) {
  return useQuery({
    queryKey: queryKeys.approvals.workflowWaiting(id ?? ""),
    queryFn: () => approvalsApi.getWorkflowWaiting(id as string),
    enabled: id !== null,
    // A count read minutes ago is not the count that will be released.
    staleTime: 0,
    gcTime: 0,
  });
}
