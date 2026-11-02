import { useQuery } from "@tanstack/react-query";
import { authApi, type InitStatus } from "@/lib/api/auth";
import { queryKeys } from "@/hooks/queries/keys";

/**
 * Reports whether the system has been initialised (at least one user exists),
 * and — on a public demo — where its public mail inbox is.
 *
 * Used by ``RegisterPage`` to decide whether to show the "first-user setup"
 * form (full registration) or the "request access" form (managed cloud), and
 * by ``LoginPage`` to point a visitor at the demo's inbox.
 *
 * Lives in Core (``src/hooks``) so that ``/register`` works without any
 * managed-cloud module — this is a self-hosting concern, not a SaaS one.
 */
export function useInitStatus(enabled = true) {
  return useQuery<InitStatus>({
    queryKey: queryKeys.admin.initStatus,
    queryFn: () => authApi.getInitStatus(),
    enabled,
    staleTime: Infinity,
  });
}
