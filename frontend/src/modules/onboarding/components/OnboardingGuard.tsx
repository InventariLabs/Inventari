import { Navigate } from "react-router-dom";
import { useOrganization } from "@/modules/settings/hooks/useOrganization";

/**
 * OnboardingGuard — redirects to /onboarding when the organisation has not
 * yet completed the profile-selection step (onboarding_completed === false).
 *
 * Null / undefined means the org was created before the onboarding feature
 * existed, so it is treated as already completed.
 */
export function OnboardingGuard({ children }: { children: React.ReactNode }) {
  const { data: org, isLoading, isFetching } = useOrganization();

  // While loading, or while a background refetch is in flight (e.g. right
  // after OnboardingPage sets the profile), do not bounce — otherwise a stale
  // `onboarding_completed: false` would redirect back to /onboarding.
  if (isLoading || isFetching || !org) return <>{children}</>;

  // Explicit false = new org that hasn't chosen a profile yet
  if (org.onboarding_completed === false) {
    return <Navigate to="/onboarding" replace />;
  }

  return <>{children}</>;
}
