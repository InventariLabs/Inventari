import { useActiveProfile } from "@/module-sdk";

/**
 * Whether the organization keeps a home rather than a business.
 *
 * A home makes jam, not lots: its screens speak of a best-before date and jar
 * labels, and never ask for a batch code — the run still files its output
 * under one, named on its own.
 */
export function useIsHomeProfile(): boolean {
  const profile = useActiveProfile();
  return profile?.seed_profile === "food_home";
}
