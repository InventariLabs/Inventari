import { api, getEveryPage } from "./client";
import type {
  Organization,
  ProductProfile,
  ProfileSwitchRequest,
  ProfileSwitchResponse,
} from "@/types";

export const onboardingApi = {
  listProfiles: async (): Promise<ProductProfile[]> => {
    return getEveryPage<ProductProfile>("/profiles");
  },

  setup: async (
    profileId: string,
    currency?: string,
    modules?: string[],
    focusModule?: string,
    organizationName?: string,
    country?: string,
    useCountryPreset?: boolean,
  ): Promise<Organization> => {
    const response = await api.post<Organization>("/onboarding/setup", {
      profile_id: profileId,
      currency,
      modules,
      focus_module: focusModule,
      organization_name: organizationName,
      country,
      use_country_preset: useCountryPreset,
      // The organization's clock — when a day starts for expiry dates,
      // inventory periods and reports. Onboarding asks the currency and
      // used to leave the zone at UTC whatever this browser said; the same
      // answer the stock-move export sends (see `stockMoves.exportXlsx`).
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    });
    return response.data;
  },

  /** The document preset onboarding offers for a country, or null. */
  countryPreset: async (country: string): Promise<string | null> => {
    const response = await api.get<{ preset: string | null }>(
      "/onboarding/country-preset",
      { params: { country } },
    );
    return response.data.preset;
  },

  /**
   * Dry-run a profile switch.
   *
   * Calls POST /onboarding/switch-profile with dry_run=true so the caller
   * can show a preview (modules to enable / disable / cascade) before the
   * user commits. Returns a `ProfileSwitchResponse` with `applied=false`
   * and no updated organization.
   */
  previewProfileSwitch: async (
    profileId: string,
  ): Promise<ProfileSwitchResponse> => {
    const body: ProfileSwitchRequest = { profile_id: profileId, dry_run: true };
    const response = await api.post<ProfileSwitchResponse>(
      "/onboarding/switch-profile",
      body,
    );
    return response.data;
  },

  /**
   * Apply a profile switch.
   *
   * Calls POST /onboarding/switch-profile with dry_run=false. The server
   * runs lifecycle hooks in a transaction, persists the new active profile
   * and returns the updated organization. Cache invalidation happens on
   * the caller side via the hook.
   */
  switchProfile: async (profileId: string): Promise<ProfileSwitchResponse> => {
    const body: ProfileSwitchRequest = {
      profile_id: profileId,
      dry_run: false,
    };
    const response = await api.post<ProfileSwitchResponse>(
      "/onboarding/switch-profile",
      body,
    );
    return response.data;
  },
};
