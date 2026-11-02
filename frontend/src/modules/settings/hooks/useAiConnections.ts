import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { aiConnectionsApi } from "@/lib/api/aiConnections";
import { queryKeys } from "@/hooks/queries/keys";
import { useAppMutation } from "@/lib/api/mutationFactory";
import type {
  AiBindingRequest,
  AiConnectionDraft,
  AiConnectionUpdate,
  AiPurpose,
} from "@/types/ai";

// ─── Queries ─────────────────────────────────────────────────────────────────

export function useAiConnections() {
  return useQuery({
    queryKey: queryKeys.aiConnections.all,
    queryFn: () => aiConnectionsApi.list(),
  });
}

export function useAiPurposes() {
  return useQuery({
    queryKey: queryKeys.aiConnections.purposes,
    queryFn: () => aiConnectionsApi.listPurposes(),
  });
}

/**
 * Whether the image automation can run in this organization.
 *
 * The registry answers with the same rule-set its client builder applies,
 * in its own field: `usable` is true exactly when the purpose will run —
 * the connection is in this organization, carries the capability, and its
 * recorded test for it did not fail; or, with nothing chosen, the env
 * fallback would serve. `bound_connection_id` is the org's raw choice and
 * answers a different question ("what did we pick"), so it says nothing
 * about whether the automation works. Only when the registry ANSWERED does
 * a "no" count as a fact: the caller's query state decides whether the
 * silence is a fact or a guess, and a screen that promises what the
 * automation will do must not speak on a guess.
 */
export function isVisionConfigured(purposes: AiPurpose[] | undefined) {
  return (
    !!purposes &&
    purposes.some(
      (purpose) => purpose.key === "vision.extract" && purpose.usable,
    )
  );
}

// ─── Mutations ───────────────────────────────────────────────────────────────

const invalidateAiCaches = (qc: ReturnType<typeof useQueryClient>) => {
  qc.invalidateQueries({ queryKey: queryKeys.aiConnections.all });
  qc.invalidateQueries({ queryKey: queryKeys.aiConnections.purposes });
  qc.invalidateQueries({ queryKey: queryKeys.aiConnections.bindings });
};

export function useCreateAiConnection(errorFallback?: string) {
  return useAppMutation(
    (vars: AiConnectionDraft) => aiConnectionsApi.create(vars),
    invalidateAiCaches,
    { errorFallback },
  );
}

export function useUpdateAiConnection(errorFallback?: string) {
  return useAppMutation(
    (vars: { id: string; data: AiConnectionUpdate }) =>
      aiConnectionsApi.update(vars.id, vars.data),
    invalidateAiCaches,
    { errorFallback },
  );
}

export function useDeleteAiConnection(errorFallback?: string) {
  return useAppMutation(
    (id: string) => aiConnectionsApi.delete(id),
    invalidateAiCaches,
    { errorFallback },
  );
}

export function useSetAiBinding(errorFallback?: string) {
  const qc = useQueryClient();
  return useAppMutation(
    (vars: AiBindingRequest) => aiConnectionsApi.setBinding(vars),
    invalidateAiCaches,
    {
      errorFallback,
      // Optimistic update: the select is controlled by the purposes query,
      // so without this it visibly snaps back to the old value until the
      // refetch lands — which read as "the dropdown cannot be changed".
      // What it writes is the org's choice, and that is exactly what the
      // field means, so the written value is true. `usable` is left to the
      // refetch this write schedules: it is the backend's verdict, and a
      // client-side guess at it would be the guess that field exists to
      // retire.
      onMutate: async (vars) => {
        await qc.cancelQueries({ queryKey: queryKeys.aiConnections.purposes });
        const previous = qc.getQueryData<AiPurpose[]>(
          queryKeys.aiConnections.purposes,
        );
        qc.setQueryData<AiPurpose[]>(queryKeys.aiConnections.purposes, (old) =>
          (old ?? []).map((p) =>
            p.key === vars.purpose_key
              ? { ...p, bound_connection_id: vars.connection_id }
              : p,
          ),
        );
        return { previous };
      },
      // Rollback only on error; the toast is the factory's job. On success
      // the invalidation refetch replaces the optimistic value with the
      // server's.
      onSettled: (_data, error, _vars, context) => {
        const ctx = context as { previous?: AiPurpose[] } | undefined;
        if (error && ctx?.previous) {
          qc.setQueryData(queryKeys.aiConnections.purposes, ctx.previous);
        }
      },
    },
  );
}

/**
 * Test a connection draft before saving. Calls POST /ai-connections/test
 * with the inline provider + key + base_url + model + capabilities.
 *
 * The backend checks credentials first, then sends one real request through
 * the feature's own parser, so the result says whether this model can do the
 * job — not merely whether the key is accepted. No cache invalidation: the
 * test does not mutate state.
 */
export function useTestAiConnection() {
  return useMutation({
    mutationFn: (
      vars: Pick<
        AiConnectionDraft,
        "provider" | "api_key" | "api_base_url" | "model_name" | "capabilities"
      >,
    ) => aiConnectionsApi.test(vars),
  });
}
