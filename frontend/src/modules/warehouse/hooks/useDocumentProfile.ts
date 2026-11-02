import { useAppMutation } from "@/lib/api/mutationFactory";
import { documentProfileApi } from "@/modules/warehouse/api/documents";
import type { DocumentProfileUpdate } from "@/modules/warehouse/types";
import { queryKeys } from "@/hooks/queries/keys";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";

export function useDocumentProfile() {
  return useModuleQuery("warehouse", {
    queryKey: queryKeys.documents.profile,
    queryFn: () => documentProfileApi.getProfile(),
    staleTime: 5 * 60 * 1000,
  });
}

export function useDocumentPresets() {
  return useModuleQuery("warehouse", {
    queryKey: queryKeys.documents.presets,
    queryFn: () => documentProfileApi.getPresets(),
    staleTime: 60 * 60 * 1000,
  });
}

/** The registered pick orders the profile's choice is made from. */
export function usePickOrderStrategies() {
  return useModuleQuery("warehouse", {
    queryKey: queryKeys.documents.pickOrderStrategies,
    queryFn: () => documentProfileApi.getPickOrderStrategies(),
    // Registered at module import time, so the list moves with a deployment.
    staleTime: 5 * 60 * 1000,
  });
}

export function useUpdateDocumentProfile() {
  return useAppMutation(
    (data: DocumentProfileUpdate) => documentProfileApi.updateProfile(data),
    (qc, data) => {
      qc.setQueryData(queryKeys.documents.profile, data);
    },
  );
}

export function useApplyDocumentPreset() {
  return useAppMutation(
    (preset: string) => documentProfileApi.applyPreset(preset),
    (qc, data) => {
      qc.setQueryData(queryKeys.documents.profile, data);
    },
  );
}
