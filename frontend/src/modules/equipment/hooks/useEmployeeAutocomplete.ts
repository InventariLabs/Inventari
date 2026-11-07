import { useQuery } from "@tanstack/react-query";
import { partnersApi } from "@/lib/api/partners";
import { queryKeys } from "@/hooks/queries/keys";

interface UseEmployeeAutocompleteParams {
  search: string;
  enabled: boolean;
}

/**
 * The employee book searched for `search`, as a query: the hook below mounts
 * it, and the checkout's address check fetches the same entry when the save
 * cannot wait for the typing to settle.
 */
export function employeeSearchQuery(search: string) {
  return {
    queryKey: queryKeys.partners.employees(search),
    queryFn: () =>
      partnersApi.list({
        type: "EMPLOYEE",
        search: search || undefined,
        limit: 20,
        is_active: true,
      }),
    staleTime: 30_000,
  };
}

export function useEmployeeAutocomplete({
  search,
  enabled,
}: UseEmployeeAutocompleteParams) {
  return useQuery({ ...employeeSearchQuery(search), enabled });
}
