import { PackageSearch } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

interface BrandLogoProps {
  /**
   * Optional i18n key for the per-profile subtitle (e.g.
   * `profiles.food_home.subtitle`). Absent → plain "Inventari" wordmark
   * (auth pages, unbranded profiles like clean_core).
   */
  subtitleKey?: string | null;
  className?: string;
}

/**
 * Inventari wordmark: package icon + "Inventari" + optional muted subtitle.
 * The subtitle is smaller and visually muted so the
 * brand stays dominant. Presentational only — the shell resolves the active
 * profile and passes `subtitleKey`.
 */
export function BrandLogo({ subtitleKey, className }: BrandLogoProps) {
  const { t } = useTranslation("common");
  return (
    <span
      className={cn(
        // The wordmark sits on `surface-card` in both themes. `text-on-primary`
        // is the brand-text token: the ramp's 700 on light, a light end on
        // dark that follows the active profile's palette. The raw steps could
        // not do it — 600 measured 3.7:1 on white, and 500 is the profile's
        // own in dark (4.05:1 under the blue palette).
        "flex items-center gap-2 text-base font-semibold text-on-primary",
        className,
      )}
    >
      <PackageSearch size={20} strokeWidth={1.5} className="shrink-0" />
      <span className="flex items-baseline gap-1.5 min-w-0">
        <span className="shrink-0">Inventari</span>
        {/* Collapsed away between flex items on screen; in the link's
            accessible name it is what keeps "Inventari" and the subtitle
            two words. */}
        {subtitleKey && " "}
        {subtitleKey && (
          <span className="text-xs font-medium text-on-muted truncate">
            {t(subtitleKey)}
          </span>
        )}
      </span>
    </span>
  );
}
