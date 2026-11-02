import { useQuery } from "@tanstack/react-query";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { apiKeysApi } from "../api";
import type { ApiKeyCreate } from "../types";
import { queryKeys } from "@/hooks/queries/keys";

export function useApiKeys() {
  return useQuery({
    queryKey: queryKeys.apiKeys.all,
    queryFn: apiKeysApi.getAll,
  });
}

/**
 * What a key may carry — read from the server, never written on the screen.
 *
 * Not cached for good: what the reader may grant follows their own
 * permissions and the organization's modules, so the issuing form reads it
 * again when it opens.
 */
export function useApiKeyCapabilities() {
  return useQuery({
    queryKey: queryKeys.apiKeys.capabilities,
    queryFn: apiKeysApi.getCapabilities,
  });
}

export function useCreateApiKey() {
  return useAppMutation(
    (data: ApiKeyCreate) => apiKeysApi.create(data),
    (qc) => {
      qc.invalidateQueries({ queryKey: queryKeys.apiKeys.all });
    },
  );
}

export function useRevokeApiKey() {
  return useAppMutation(
    (id: string) => apiKeysApi.revoke(id),
    (qc) => {
      qc.invalidateQueries({ queryKey: queryKeys.apiKeys.all });
    },
  );
}
