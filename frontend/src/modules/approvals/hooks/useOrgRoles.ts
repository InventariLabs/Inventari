import { useQuery } from "@tanstack/react-query";
import { rolesApi } from "@/lib/api/admin";
import { queryKeys } from "@/hooks/queries/keys";

/**
 * useOrgRoles -- fetches the list of RBAC roles available in the
 * caller's organisation via GET /api/v1/roles.
 *
 * The router enforces SYSTEM_CONFIG_WRITE, so a workflow editor
 * without admin permissions may receive a 403. Consumers MUST
 * tolerate the error and fall back to a static role list --
 * see `DEFAULT_ROLE_FALLBACK` in
 * `modules/approvals/components/ApprovalWorkflowEditor.tsx`.
 */
export function useOrgRoles() {
  return useQuery({
    queryKey: queryKeys.users.orgRoles,
    queryFn: () => rolesApi.list(),
    staleTime: 60_000,
    retry: false,
  });
}
