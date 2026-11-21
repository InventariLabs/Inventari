import { useQuery } from "@tanstack/react-query";
import { usersApi } from "@/lib/api/admin";
import { queryKeys } from "@/hooks/queries/keys";
import { approvalsApi } from "@/modules/approvals/api/approvals";

export function useOrgMembers() {
  return useQuery({
    queryKey: queryKeys.users.orgMembers,
    queryFn: () => usersApi.getOrgMembers(),
    staleTime: 30_000,
  });
}

/**
 * Who among the members could decide a stage that names them. Asked only by
 * the picker that names approvers, so a person who cannot see approvals is
 * marked before the save refuses a stage that names only such people.
 */
export function usePeopleWhoCanDecide(enabled: boolean) {
  return useQuery({
    queryKey: [...queryKeys.approvals.workflows, "approvers"],
    queryFn: () => approvalsApi.listPeopleWhoCanDecide(),
    enabled,
    staleTime: 30_000,
  });
}
