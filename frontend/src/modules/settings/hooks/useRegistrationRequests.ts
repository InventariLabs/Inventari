import { useQuery } from "@tanstack/react-query";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { authApi } from "@/lib/api/auth";
import type { RegistrationRequest } from "@/types";
import { queryKeys } from "@/hooks/queries/keys";

/** Pending registration requests (admin only — the API answers 403 otherwise). */
export function useRegistrationRequests() {
  return useQuery<RegistrationRequest[]>({
    queryKey: queryKeys.admin.registrationRequests,
    queryFn: () => authApi.getRegistrationRequests(),
  });
}

export function useApproveRegistrationRequest() {
  return useAppMutation(
    (requestId: string) => authApi.approveRegistrationRequest(requestId),
    (qc) => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.registrationRequests });
    },
  );
}

export function useRejectRegistrationRequest() {
  return useAppMutation(
    (requestId: string) => authApi.rejectRegistrationRequest(requestId),
    (qc) => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.registrationRequests });
    },
  );
}
