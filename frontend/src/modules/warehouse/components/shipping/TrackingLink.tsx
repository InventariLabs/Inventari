import { useTranslation } from "react-i18next";
import { ExternalLink } from "lucide-react";

interface Props {
  trackingNumber?: string | null;
  trackingUrl?: string | null;
}

/**
 * A tracking number, opening the carrier's tracking page where one is known.
 *
 * The server builds the link from the organization's templates and the
 * built-in ones; without a link the number is shown as it is, so a carrier
 * nobody configured still has its number on screen.
 */
export function TrackingLink({ trackingNumber, trackingUrl }: Props) {
  const { t } = useTranslation("warehouse");
  if (!trackingNumber) return <span className="text-on-muted">—</span>;
  if (!trackingUrl) return <span className="font-mono">{trackingNumber}</span>;
  return (
    <a
      href={trackingUrl}
      target="_blank"
      rel="noopener noreferrer"
      // Inline, not inline-flex: a number longer than its column wraps
      // inside the text, with the icon after its last character.
      className="font-mono text-on-primary hover:underline underline-offset-2"
      aria-label={t("shipping.trackAria", { number: trackingNumber })}
    >
      {trackingNumber}
      <ExternalLink
        size={12}
        aria-hidden="true"
        className="ml-1 inline align-baseline"
      />
    </a>
  );
}
