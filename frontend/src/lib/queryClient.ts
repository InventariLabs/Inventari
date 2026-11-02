import { QueryClient } from "@tanstack/react-query";
import { shouldRetryQuery } from "@/lib/errors";

/**
 * Shared QueryClient singleton.
 *
 * Lives outside main.tsx so non-React code (e.g. authStore) can clear the
 * cache on auth changes — otherwise a new login would see the previous
 * user's cached queries (org, items, ...) until a hard reload.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: shouldRetryQuery,
      refetchOnWindowFocus: false,
      staleTime: 1000 * 60 * 5,
    },
  },
});
