import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { LucideIcon } from "lucide-react";

interface RelatedScreen {
  to: string;
  icon: LucideIcon;
  label: string;
}

/**
 * The screens that carry on from a Configuration section: navigation, set
 * apart from the fields above it so a link is never mistaken for a setting.
 */
export function RelatedScreens({ screens }: { screens: RelatedScreen[] }) {
  const { t } = useTranslation("warehouse");
  return (
    <nav
      aria-label={t("configuration.related")}
      className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border pt-4"
    >
      <span className="text-xs font-medium text-on-muted">
        {t("configuration.related")}
      </span>
      {screens.map(({ to, icon: Icon, label }) => (
        <Link
          key={to}
          to={to}
          className="inline-flex min-h-11 items-center gap-1.5 rounded-md text-sm font-medium text-primary-600 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 md:min-h-0"
        >
          <Icon size={16} aria-hidden="true" />
          {label}
        </Link>
      ))}
    </nav>
  );
}
