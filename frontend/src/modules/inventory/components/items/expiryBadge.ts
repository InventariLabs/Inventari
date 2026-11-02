import type { BadgeProps } from "@/components/ui/Badge";
import type { ExpiryState } from "@/utils/helpers";

/**
 * One expiry state → one badge colour, shared by the table row and the mobile
 * card so the two views cannot drift apart.
 */
export const EXPIRY_BADGE_VARIANT: Record<ExpiryState, BadgeProps["variant"]> =
  {
    expired: "danger",
    expiring: "warning",
    ok: "secondary",
  };
