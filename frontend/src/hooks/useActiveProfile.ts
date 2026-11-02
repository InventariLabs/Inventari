import { useOrganization } from "@/modules/settings/hooks/useOrganization";
import { useProfiles } from "@/modules/onboarding/hooks/useOnboarding";
import type { ProductProfile } from "@/types";

/**
 * Resolves the organization's active product profile.
 *
 * Shared by the shell branding and `useProfileTheme` so the
 * org + profiles lookup stays in one place — and so core components import
 * a core hook instead of module internals (eslint `no-restricted-imports`
 * forbids `@/modules/*` imports in `src/components/`).
 */
export function useActiveProfile(): ProductProfile | null {
  const { data: org } = useOrganization();
  const { data: profiles } = useProfiles();
  return profiles?.find((p) => p.id === org?.active_profile_id) ?? null;
}
