import { useQuery, useMutation } from "@tanstack/react-query";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { onboardingApi } from "@/lib/api/onboarding";
import type { ProductProfile, ProfileSwitchResponse } from "@/types";
import { queryKeys } from "@/hooks/queries/keys";
import { invalidation } from "@/lib/api/invalidation";

export function useProfiles() {
  return useQuery<ProductProfile[]>({
    queryKey: queryKeys.onboarding.profiles,
    queryFn: () => onboardingApi.listProfiles(),
    staleTime: Infinity,
  });
}

/** Whether the country comes with a document preset the screen can offer. */
export function useCountryPreset(country: string) {
  return useQuery<string | null>({
    queryKey: queryKeys.onboarding.countryPreset(country),
    queryFn: () => onboardingApi.countryPreset(country),
    enabled: country !== "",
    staleTime: Infinity,
  });
}

export function useOnboardingSetup() {
  return useAppMutation(
    ({
      profileId,
      currency,
      modules,
      focusModule,
      organizationName,
      country,
      useCountryPreset,
    }: {
      profileId: string;
      currency?: string;
      modules?: string[];
      focusModule?: string;
      organizationName?: string;
      country?: string;
      useCountryPreset?: boolean;
    }) =>
      onboardingApi.setup(
        profileId,
        currency,
        modules,
        focusModule,
        organizationName,
        country,
        useCountryPreset,
      ),
    (qc) => {
      invalidation.organization(qc);
      invalidation.modules(qc);
    },
  );
}

/**
 * Preview a profile switch without committing it.
 *
 * Uses a plain `useMutation` (not `useAppMutation`) because the request is
 * read-only: no caches need invalidation. The caller decides what to do
 * with the returned diff.
 */
export function useProfileSwitchPreview() {
  return useMutation<ProfileSwitchResponse, Error, string>({
    mutationFn: (profileId: string) =>
      onboardingApi.previewProfileSwitch(profileId),
  });
}

/**
 * Apply a profile switch. After a successful response, invalidates:
 *   - organization (active_profile_id, enabled_modules)
 *   - my-modules (modules enabled/disabled by the switch)
 *   - all ["stats"] caches (counts may shift)
 */
export function useProfileSwitchApply() {
  return useAppMutation<ProfileSwitchResponse, string>(
    (profileId: string) => onboardingApi.switchProfile(profileId),
    (qc) => {
      invalidation.organization(qc);
      invalidation.modules(qc);
      invalidation.stats(qc);
    },
    {
      errorFallback: "Failed to switch workspace mode",
    },
  );
}
