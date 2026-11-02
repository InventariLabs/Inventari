import { useQuery } from "@tanstack/react-query";
import { usersApi } from "@/lib/api/admin";
import { queryKeys } from "@/hooks/queries/keys";

export function useOrgMembers() {
  return useQuery({
    queryKey: queryKeys.users.orgMembers,
    queryFn: () => usersApi.getOrgMembers(),
    staleTime: 30_000,
  });
}
