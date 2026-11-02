import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ShoppingBasket, Monitor, Box, type LucideIcon } from "lucide-react";
import { useActiveProfile } from "@/hooks/useActiveProfile";
import { useHasPermission } from "@/hooks/useHasPermission";
import { useProfileLabels } from "@/modules/settings/hooks/useProfileLabels";

const ICONS: Record<string, LucideIcon> = {
  ShoppingBasket,
  Monitor,
  Box,
};

/**
 * ActiveProfilePill — renders the org's active product profile in the
 * Launcher header (admin-only) and links to /settings/my-modules, the one
 * screen that decides which modules the workspace shows.
 */
export function ActiveProfilePill() {
  const { t } = useTranslation("launcher");
  const isAdmin = useHasPermission("admin:access");
  const profile = useActiveProfile();
  const profileLabels = useProfileLabels();

  if (!isAdmin || !profile) return null;

  const Icon = (profile.icon && ICONS[profile.icon]) || Box;

  return (
    <Link
      to="/settings/my-modules"
      className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-card px-3 py-1.5 text-xs font-medium text-on-secondary hover:bg-surface-raised transition-colors"
    >
      <Icon size={14} />
      {profileLabels(profile).name}
      <span className="text-on-muted">· {t("activeProfile.change")}</span>
    </Link>
  );
}
