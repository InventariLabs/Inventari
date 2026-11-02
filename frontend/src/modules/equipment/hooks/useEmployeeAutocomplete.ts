import { useQuery } from "@tanstack/react-query";
import { partnersApi } from "@/lib/api/partners";
import { queryKeys } from "@/hooks/queries/keys";

interface UseEmployeeAutocompleteParams {
  search: string;
  enabled: boolean;
}

export function useEmployeeAutocomplete({
  search,
  enabled,
}: UseEmployeeAutocompleteParams) {
  return useQuery({
    queryKey: queryKeys.partners.employees(search),
    queryFn: () =>
      partnersApi.list({
        type: "EMPLOYEE",
        search: search || undefined,
        limit: 20,
        is_active: true,
      }),
    enabled,
    staleTime: 30_000,
  });
}
